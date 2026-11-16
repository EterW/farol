"""Sessão ao vivo (uma por aba do navegador). Usa o DerivHub compartilhado e exatamente o mesmo
código do backtest: estrategias.gerar_sinais, backtest.executar/resolver (via ranking) e
timeframes.agregar. A estratégia líder (com histerese) e os avisos vêm de binarias/avisos.py.

Troca de ativo/tempo gráfico: cada pedido "assinar" traz um ID de sessão (`sid`). A sessão para TUDO o
que era do contexto anterior (tarefas, séries, operações em aberto, líder, avisos) e toda mensagem
enviada leva o `sid` do contexto em que foi gerada: o navegador descarta as que não forem do atual."""

import asyncio
import contextlib
import csv
import json
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone

import pandas as pd

from . import assistente, mercado, progresso, scanner, sinal, veredito
from .avisos import MotorAvisos, SeletorLider, nome_ativo
from .backtest import ConfigBacktest, resolver
from .config import (
    ATIVOS_SCANNER,
    ATRASO_MAX_VELAS,
    CACHE_RANKING_MAX,
    CICLO_SESSAO,
    EMPATE_PADRAO,
    FOLGA_FECHAMENTO,
    JANELA_ENTRADA_FRACAO,
    JANELA_ENTRADA_MAX,
    JANELA_ENTRADA_MIN,
    JANELA_RANKING,
    MIN_OPERACOES,
    N_HISTORICO,
    N_VELAS_GRAFICO,
    N_VELAS_PREVIA,
    PASTA_RESULTADOS,
    PROGRESSO_LIMITE,
    PROGRESSO_LIMITE_MAX,
    PROGRESSO_LIMITE_MIN,
    TEMPO_LIMITE_CARGA,
)
from .estrategias import ESTRATEGIAS, POR_ID
from .hub import DerivHub, SerieVelas
from .log import obter
from .ranking import calcular_ranking
from .timeframes import agregar, granularidade_base, linhas_ohlc, nome_timeframe, parse_timeframe

log = obter("sessao")

CSV_SINAIS = os.path.join(PASTA_RESULTADOS, "sinais_ao_vivo.csv")
COLUNAS_CSV = [
    "data_sinal",
    "data_entrada",
    "ativo",
    "timeframe",
    "estrategia",
    "principal",
    "direcao",
    "expiracao",
    "preco_entrada",
    "preco_saida",
    "resultado",
]


NOMES = {e.id: e.nome for e in ESTRATEGIAS}

# ranking por (ativo, tempo gráfico, última vela, expiração, payout, empate, marcadas): voltar a um ativo
# na mesma vela não recalcula nada. É o mesmo resultado (mesmas velas = mesmo cálculo).
_CACHE_RANKING: "OrderedDict[tuple, dict]" = OrderedDict()


def _ranking_em_cache(chave: tuple, calcular) -> dict:
    if chave in _CACHE_RANKING:
        _CACHE_RANKING.move_to_end(chave)
        return _CACHE_RANKING[chave]
    r = calcular()
    _CACHE_RANKING[chave] = r
    while len(_CACHE_RANKING) > CACHE_RANKING_MAX:
        _CACHE_RANKING.popitem(last=False)
    return r


class NavegadorFechado(Exception):
    """O navegador fechou a aba/conexão: a sessão para de enviar."""


def fmt_data(epoch: int) -> str:
    """Epoch -> 'AAAA-MM-DD hh:mm:ss' (UTC)."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def gravar_csv(linha: dict) -> None:
    """Acrescenta no CSV de sinais. Se o arquivo tiver o cabeçalho antigo, ele é renomeado."""
    if os.path.exists(CSV_SINAIS):
        with open(CSV_SINAIS, encoding="utf-8-sig") as f:
            cabecalho = f.readline().strip().split(",")
        if cabecalho != COLUNAS_CSV:
            os.replace(CSV_SINAIS, CSV_SINAIS.replace(".csv", f"_antigo_{int(time.time())}.csv"))
    novo = not os.path.exists(CSV_SINAIS)
    with open(CSV_SINAIS, "a", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: acentos no Excel
        w = csv.DictWriter(f, fieldnames=COLUNAS_CSV)
        if novo:
            w.writeheader()
        w.writerow(linha)


def _limpar(o):
    """NaN/inf -> None (o JSON.parse do navegador não aceita NaN); numpy -> Python."""
    if isinstance(o, dict):
        return {k: _limpar(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set, frozenset)):
        return [_limpar(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        o = o.item()
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    return o


class Sessao:
    """Uma aba conectada: ativo principal, scanner, líder, avisos e registro em CSV."""

    def __init__(self, navegador, hub: DerivHub):
        self.nav = navegador
        self.hub = hub
        self.tarefas: list[asyncio.Task] = []
        self.series: list[tuple[SerieVelas, bool]] = []  # (série, é o ativo principal?)
        self.sid: str | None = None  # ID do contexto atual (ativo + tempo gráfico) pedido pelo navegador
        self.principal_pronto = asyncio.Event()
        self.ativas: set[str] = set(POR_ID)
        self.observacao = False  # modo observação (só muda o que a tela mostra, nunca o ENTRAR)
        self.seletor = SeletorLider()
        self.motor = MotorAvisos(limite=PROGRESSO_LIMITE)
        self.ranking: dict | None = None
        self.analise: dict | None = None
        self.operacoes: dict[str, dict] = {}
        self._seq = 0
        self._lock_envio = asyncio.Lock()
        self.fechado = False
        self.ultimo_veredito: dict | None = None
        self.simbolo: str = ""
        self.tf: str = ""

    # ------------------------------------------------------------------ envio
    async def enviar(self, tipo: str, **conteudo) -> None:
        """Envia uma mensagem JSON ao navegador (NaN viram null)."""
        if self.fechado:
            raise NavegadorFechado()
        texto = json.dumps(_limpar({"tipo": tipo, "sid": self.sid, **conteudo}), default=str)  # sid de AGORA
        try:
            async with self._lock_envio:
                await self.nav.send_text(texto)
        except Exception as e:
            self.fechado = True
            raise NavegadorFechado() from e

    async def status(self, texto: str, nivel: str = "info") -> None:
        """Mensagem de status para a tela."""
        await self.enviar("status", texto=texto, nivel=nivel)

    async def carga(self, etapa: str, texto: str, feito: int | None = None, total: int | None = None) -> None:
        """Progresso do carregamento (etapa "velas", "estrategias" ou "erro") para a tela."""
        await self.enviar(
            "carga", etapa=etapa, texto=texto, feito=feito, total=total, simbolo=self.simbolo, timeframe=self.tf
        )

    async def avisar(self, lista: list[dict]) -> None:
        """Envia os avisos (som/notificação) decididos pelo motor."""
        for a in lista:
            await self.enviar("aviso", **a)

    @property
    def ativo(self) -> str:
        """Nome do ativo para os textos (ex.: EUR/USD)."""
        return nome_ativo(self.simbolo)

    # ------------------------------------------------------------------ preferências do navegador
    async def configurar(self, msg: dict) -> None:
        """Aplica preferências JÁ do formato certo (o servidor valida antes): ativas, observação,
        avisar candidatas não comprovadas e limite do aviso de formação."""
        if isinstance(msg.get("ativas"), list):
            novas = {i for i in msg["ativas"] if i in POR_ID}
            if novas != self.ativas:
                self.ativas = novas
                if self.ranking is not None:  # desmarcar a líder tira ela do posto na hora
                    troca = self.seletor.atualizar(self.ranking, self.ativas, contar=False)
                    self.ranking = self._com_lider(self.ranking)
                    if troca["trocou"]:
                        await self.avisar(self.motor.fechamento({}, 0, self.ativo, troca, NOMES))
        if isinstance(msg.get("observacao"), bool):
            self.observacao = msg["observacao"]
        if isinstance(msg.get("avisar_obs"), bool):
            self.motor.avisar_obs = msg["avisar_obs"]
        lim = msg.get("limite_formacao")
        if isinstance(lim, int) and not isinstance(lim, bool) and PROGRESSO_LIMITE_MIN <= lim <= PROGRESSO_LIMITE_MAX:
            self.motor.limite = lim
        if isinstance(msg.get("bloqueio_dia"), bool):  # "Minha banca": limite do dia atingido
            self.motor.bloqueado = msg["bloqueio_dia"]

    def _com_lider(self, ranking: dict) -> dict:
        s = self.seletor
        return {
            **ranking,
            "lider": s.atual,
            "lider_info": {
                "desafiante": s.desafiante,
                "contagem": s.contagem,
                "confirmacao": s.velas_confirmacao,
                "margem_ic": s.margem_ic,
            },
        }

    # ------------------------------------------------------------------ controle
    async def iniciar(
        self, simbolo: str, timeframe: str, expiracao: int, payout: float, sid: str | None = None
    ) -> None:
        """Começa a acompanhar um ativo/timeframe. Antes, descarta TODO o estado do contexto anterior."""
        await self.parar()
        self.sid = sid
        self.principal_pronto = asyncio.Event()
        self.analise = None
        self.operacoes = {}
        try:
            seg = parse_timeframe(timeframe)
            self.cfg = ConfigBacktest(expiracao=max(1, int(expiracao)), payout=float(payout), empate=EMPATE_PADRAO)
        except ValueError as e:
            await self.status(str(e), "erro")
            return
        self.simbolo, self.seg, self.tf = simbolo, seg, nome_timeframe(seg)
        self.gran = granularidade_base(seg)
        self.fator = seg // self.gran
        self.n_base = (N_HISTORICO + 2) * self.fator
        self.hold = min(
            JANELA_ENTRADA_MAX, max(JANELA_ENTRADA_MIN, seg * JANELA_ENTRADA_FRACAO)
        )  # quanto tempo mostrar ENTRAR AGORA / CONFLITO
        self.ranking = None
        self.seletor = SeletorLider()
        self.motor = MotorAvisos(
            limite=self.motor.limite, avisar_obs=self.motor.avisar_obs, bloqueado=self.motor.bloqueado
        )
        self.recentes: dict[str, dict] = {}
        self.decisao_fixa: dict | None = None
        self._cache_prog: tuple = (None, None)
        self.tarefas = [
            asyncio.create_task(self._proteger(c, nome))
            for c, nome in (
                (self._rodar(), "ativo"),
                (self._rodar_scanner(), "scanner"),
                (self._vigiar_conexao(), "conexão"),
            )
        ]

    async def parar(self) -> None:
        """Para as tarefas, libera as séries e registra operações sem resultado como CANCELADO."""
        for t in self.tarefas:
            t.cancel()
        for t in self.tarefas:
            with contextlib.suppress(asyncio.CancelledError, NavegadorFechado):
                await t  # as demais exceções já foram tratadas em _proteger
        self.tarefas = []
        for s, principal in self.series:
            self.hub.liberar(s, prioridade=principal)
        self.series = []
        for op in self.operacoes.values():  # operações sem resultado ficam registradas
            self._registrar(op, None, None, "CANCELADO")
        self.operacoes.clear()

    async def _proteger(self, coro, nome: str) -> None:
        try:
            await coro
        except (asyncio.CancelledError, NavegadorFechado):
            raise
        except Exception as e:
            log.exception("Sessão %s %s: tarefa '%s' falhou", self.simbolo, self.tf, nome)
            with contextlib.suppress(NavegadorFechado):
                await self.status(f"Erro interno ({nome}): {e}. Detalhes em resultados/erros.log", "erro")

    async def _obter(self, simbolo: str, principal: bool = False) -> SerieVelas:
        s = await self.hub.obter_serie(simbolo, self.gran, self.n_base, prioridade=principal)
        self.series.append((s, principal))
        return s

    # ------------------------------------------------------------------ velas
    def _velas(self, s: SerieVelas) -> tuple[pd.DataFrame, pd.DataFrame]:
        fechadas, formando = agregar(s.df(), self.seg, self.gran, self.hub.agora() - FOLGA_FECHAMENTO)
        return fechadas.tail(N_HISTORICO).reset_index(drop=True), formando

    def _proximo_fechamento(self) -> int:
        a = self.hub.agora()
        return int(a - a % self.seg + self.seg)

    # ------------------------------------------------------------------ conexão
    async def _vigiar_conexao(self) -> None:
        ultimo = None
        while True:
            st = self.hub.status
            chave = (st["estado"], st["texto"])
            if chave != ultimo:
                ultimo = chave
                await self.enviar("conexao", estado=st["estado"], texto=st["texto"], quedas=st["quedas"])
            await asyncio.sleep(1)

    # ------------------------------------------------------------------ ativo principal
    async def _esperar_velas(self, s: SerieVelas) -> bool:
        """Espera o histórico do ativo principal, mandando o progresso. False = desistiu (tempo limite)."""
        alvo = s.n_base
        limite = time.monotonic() + TEMPO_LIMITE_CARGA
        ultimo = None
        while not s.pronta.is_set():
            if time.monotonic() > limite:
                return False
            feito = min(s.baixadas, alvo) // max(1, self.fator)
            if feito != ultimo:
                ultimo = feito
                await self.carga("velas", f"Carregando velas de {self.ativo} {self.tf}…", feito, N_HISTORICO)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(s.pronta.wait(), 0.25)
        return True

    async def _rodar(self) -> None:
        try:
            await self._rodar_principal()
        finally:
            self.principal_pronto.set()  # o scanner começa mesmo se o principal falhar

    async def _rodar_principal(self) -> None:
        await self.carga("velas", f"Carregando velas de {self.ativo} {self.tf}…", 0, N_HISTORICO)
        s = await self._obter(self.simbolo, principal=True)
        if not await self._esperar_velas(s):
            await self.carga(
                "erro",
                f"A Deriv não entregou as velas de {self.ativo} {self.tf} em {TEMPO_LIMITE_CARGA:.0f} s. "
                "Verifique a internet e toque em “Tentar de novo”.",
            )
            return
        if not s.velas:
            await self.carga("erro", f"A Deriv não devolveu velas de {self.ativo} {self.tf}: {s.erro or 'sem dados'}.")
            return
        self.serie = s
        self.df, formando = self._velas(s)
        if len(self.df) < 2:
            await self.carga("erro", f"Histórico insuficiente para {self.ativo} {self.tf}.")
            return
        self.ultima_fechada = int(self.df["epoch"].iat[-1])
        await self._inicializar(formando)
        self.principal_pronto.set()
        if s.mercado_fechado:
            await self.status(f"Mercado fechado: mostrando só o histórico de {self.simbolo} {self.tf}.", "aviso")
        else:
            await self.status(f"Ao vivo: {self.simbolo} {self.tf}", "ok")

        versao, ultima_formando, ultimo_estado, ultimo_calc = -1, None, 0.0, 0.0
        while True:
            await asyncio.sleep(CICLO_SESSAO)
            if s.versao == versao and time.time() - ultimo_calc < 1:
                continue
            versao, ultimo_calc = s.versao, time.time()
            fechadas, formando = self._velas(s)
            if len(fechadas) and int(fechadas["epoch"].iat[-1]) > self.ultima_fechada:
                novas = fechadas[fechadas["epoch"] > self.ultima_fechada]
                self.ultima_fechada = int(fechadas["epoch"].iat[-1])
                self.df = fechadas
                for v in linhas_ohlc(novas):
                    await self.enviar("vela", v=v)
                await self._ao_fechar(formando, len(novas))
                ultimo_estado = 0.0
            atual = linhas_ohlc(formando)[0] if len(formando) else None
            if atual and atual != ultima_formando:
                ultima_formando = atual
                await self.enviar("vela", v=atual)
            if time.time() - ultimo_estado >= 1:
                ultimo_estado = time.time()
                await self._enviar_estado(formando)

    def _calcular(self, df: pd.DataFrame, formando: pd.DataFrame, ativas: set, ao_progresso=None) -> tuple[dict, dict]:
        cfg = self.cfg
        chave = (self.simbolo, self.tf, int(df["epoch"].iat[-1]), len(df), cfg.expiracao, cfg.payout, cfg.empate)
        chave += (frozenset(ativas),)
        r = _ranking_em_cache(
            chave,
            lambda: calcular_ranking(
                df, cfg, JANELA_RANKING, MIN_OPERACOES, elegiveis=ativas, ao_progresso=ao_progresso
            ),
        )
        a = mercado.analisar(df, formando, nome=f"{self.simbolo.removeprefix('frx')} {self.tf}")
        return r, a

    async def _calcular_com_progresso(self, df: pd.DataFrame, formando: pd.DataFrame, ativas: set):
        """Ranking em segundo plano (thread), mandando "calculando estratégias k de 11" para a tela."""
        loop = asyncio.get_running_loop()
        fila: asyncio.Queue = asyncio.Queue()

        def ao_progresso(feitas: int, total: int, nome: str) -> None:
            loop.call_soon_threadsafe(fila.put_nowait, (feitas, total, nome))

        tarefa = asyncio.ensure_future(asyncio.to_thread(self._calcular, df, formando, ativas, ao_progresso))
        try:
            while not tarefa.done():
                with contextlib.suppress(asyncio.TimeoutError):
                    feitas, total, nome = await asyncio.wait_for(fila.get(), 0.2)
                    if feitas < total:
                        texto = f"Calculando estratégias {feitas + 1} de {total} ({nome})…"
                        await self.carga("estrategias", texto, feitas, total)
            return await tarefa
        finally:
            tarefa.cancel()  # se a sessão trocar de ativo, o resultado atrasado é descartado

    async def _inicializar(self, formando: pd.DataFrame) -> None:
        df = self.df
        # setas do histórico (só a parte que aparece no gráfico)
        grafico = df.tail(N_VELAS_GRAFICO)
        inicio = int(grafico["epoch"].iat[0])
        marcas = []
        for est in ESTRATEGIAS:
            try:
                s = est.gerar_sinais(df)
            except Exception:
                log.exception("Estratégia %s falhou no histórico", est.id)
                continue
            for i in s.index[s.isin(["CALL", "PUT"])]:
                t = int(df["epoch"].iat[i])
                if t >= inicio:
                    marcas.append({"t": t, "id": est.id, "dir": s.iat[i]})
        velas = linhas_ohlc(grafico) + linhas_ohlc(formando)
        await self.enviar(
            "historico",
            simbolo=self.simbolo,
            timeframe=self.tf,
            seg=self.seg,
            expiracao=self.cfg.expiracao,
            payout=self.cfg.payout,
            casas=self.serie.casas,
            janela_entrada=self.hold,
            velas=velas,
            sinais=marcas,
            n_velas=len(df),
        )
        # as velas já estão na tela; agora o ranking (em thread, com progresso)
        ranking, analise = await self._calcular_com_progresso(df, formando, set(self.ativas))
        self.seletor.atualizar(ranking, self.ativas)
        ranking = self._com_lider(ranking)
        self.ranking, self.analise = ranking, analise
        await self._enviar_analise(ranking, analise)
        dec = sinal.decidir(ranking, {}, {}, self.ativas, lider=self.seletor.atual)
        await self.enviar("decisao", **dec, novo=False, t=self.ultima_fechada, veredito=self._veredito(dec, {}))

    def _veredito(self, dec: dict, estados: dict, prog: dict | None = None) -> dict:
        humano = (self.analise or {}).get("humano")
        assert self.ranking is not None  # só é chamado depois do primeiro ranking
        ver = veredito.montar(dec, self.ranking, humano, self.observacao, estados, self.ativas, prog)
        self.ultimo_veredito = ver
        return ver

    def dados_assistente(self) -> tuple[dict, tuple] | None:
        """JSON (só dados já calculados) e chave de cache (ativo, tempo, vela) para o assistente. None = sem dados."""
        if self.ranking is None or not getattr(self, "simbolo", None):
            return None
        humano = (self.analise or {}).get("humano")
        dados = assistente.montar_dados(self.ativo, self.tf, self.ultimo_veredito, humano, self.ranking)
        return dados, (self.simbolo, self.tf, getattr(self, "ultima_fechada", None))

    async def _enviar_analise(self, ranking: dict, analise: dict) -> None:
        await self.enviar("ranking", **ranking)
        await self.enviar("analise", **analise)

    async def _ao_fechar(self, formando: pd.DataFrame, n_novas: int) -> None:
        df = self.df
        epochs = df["epoch"].to_numpy()
        exp = self.cfg.expiracao

        # 1) resolve operações cuja vela de expiração fechou (mesma regra do backtest)
        for est_id, op in list(self.operacoes.items()):
            depois = df[epochs > op["t"]]
            if len(depois) >= exp:
                entrada = float(depois["open"].iat[0])
                saida = float(depois["close"].iat[exp - 1])
                res = resolver(op["dir"], entrada, saida, self.cfg.empate)
                op["t_entrada"] = int(depois["epoch"].iat[0])
                self._registrar(op, entrada, saida, res)
                del self.operacoes[est_id]
                await self.enviar(
                    "resultado",
                    op=op["n"],
                    id=est_id,
                    resultado=res,
                    entrada=entrada,
                    saida=saida,
                    principal=bool(op.get("principal")),
                    ativo=self.simbolo,
                    timeframe=self.tf,
                )
                await self.avisar(self.motor.resultado(op, res, self.ativo))

        # 2) ranking + análise na vela que acabou de fechar (em thread: não trava o servidor)
        ativas = set(self.ativas)
        ranking, analise = await asyncio.to_thread(self._calcular, df, formando, ativas)
        troca = self.seletor.atualizar(ranking, ativas)
        ranking = self._com_lider(ranking)
        self.ranking, self.analise = ranking, analise
        sinais = {linha["id"]: linha["sinal"] for linha in ranking["linhas"]}
        dec = sinal.decidir(ranking, sinais, {}, ativas, lider=self.seletor.atual)
        t = int(epochs[-1])
        if n_novas > 1:
            log.warning(
                "%s %s: %d velas fecharam de uma vez (queda/atraso); só a última foi avaliada",
                self.simbolo,
                self.tf,
                n_novas,
            )

        # 3) registra os sinais das estratégias marcadas (teste ao vivo) — uma operação por estratégia
        for est_id, d in sinais.items():
            if not d:
                continue
            nome = POR_ID[est_id].nome
            registrado = est_id in ativas and est_id not in self.operacoes
            principal = dec["estado"] == "ENTRAR" and est_id == dec["estrategia"]
            if registrado:
                self._seq += 1
                self.operacoes[est_id] = {
                    "n": self._seq,
                    "id": est_id,
                    "nome": nome,
                    "dir": d,
                    "t": t,
                    "t_entrada": t + self.seg,
                    "principal": principal,
                }
                self.recentes[est_id] = {"dir": d, "ate": time.time() + self.hold}
            await self.enviar(
                "sinal",
                op=self._seq if registrado else None,
                id=est_id,
                nome=nome,
                dir=d,
                t=t,
                registrado=registrado,
                principal=principal,
                ativo=self.simbolo,
                timeframe=self.tf,
            )

        # 4) decisão principal (fica fixa por alguns segundos se for ENTRAR/CONFLITO)
        self.decisao_fixa = {**dec, "ate": time.time() + self.hold} if dec["estado"] in ("ENTRAR", "CONFLITO") else None
        await self._enviar_analise(ranking, analise)
        estados = {k: {"estado": "SINAL", "dir": v} for k, v in sinais.items() if v}
        ver = self._veredito(dec, estados)
        await self.enviar("decisao", **dec, novo=True, t=t, veredito=ver)
        await self.avisar(self.motor.fechamento(ver, t + self.seg, self.ativo, troca, NOMES))

    def _registrar(self, op: dict, entrada, saida, resultado: str) -> None:
        try:
            gravar_csv(
                {
                    "data_sinal": fmt_data(op["t"]),
                    "data_entrada": fmt_data(op["t_entrada"]),
                    "ativo": self.simbolo,
                    "timeframe": self.tf,
                    "estrategia": op["nome"],
                    "principal": "sim" if op.get("principal") else "não",
                    "direcao": op["dir"],
                    "expiracao": self.cfg.expiracao,
                    "preco_entrada": "" if entrada is None else entrada,
                    "preco_saida": "" if saida is None else saida,
                    "resultado": resultado,
                }
            )
        except OSError:
            log.exception("Não foi possível gravar %s (arquivo aberto no Excel?)", CSV_SINAIS)

    def _alvo_progresso(self) -> str | None:
        """De quem medir o progresso completo: a líder; sem líder, a candidata do modo observação."""
        if self.seletor.atual and self.seletor.atual in self.ativas:
            return self.seletor.atual
        if self.observacao and self.ranking:
            cand = veredito.candidata(self.ranking, self.ativas)
            return cand["id"] if cand else None
        return None

    def _formacao(self, formando: pd.DataFrame) -> tuple[dict, dict | None]:
        """Condições de todas as estratégias na vela em formação (uma passada cada) + progresso
        completo da líder/candidata. Roda em thread."""
        if not len(formando) or not len(self.df):
            return {}, None
        parcial = pd.concat([self.df.tail(N_VELAS_PREVIA), formando], ignore_index=True)
        rapidas = {}
        for est in ESTRATEGIAS:
            try:
                rapidas[est.id] = progresso.condicoes_agora(est, parcial)
            except Exception:
                log.exception("Estratégia %s falhou na vela em formação", est.id)
        alvo = self._alvo_progresso()
        prog = None
        if alvo in rapidas:
            chave = (alvo, tuple(parcial.iloc[-1][["epoch", "open", "high", "low", "close"]]))
            if self._cache_prog[0] == chave:
                prog = self._cache_prog[1]
            else:
                prog = progresso.calcular(POR_ID[alvo], parcial)
                self._cache_prog = (chave, prog)
        return rapidas, prog

    async def _enviar_estado(self, formando: pd.DataFrame) -> None:
        if self.ranking is None:
            return
        rapidas, prog = await asyncio.to_thread(self._formacao, formando)
        agora = time.time()
        lider = self.seletor.atual
        limite = self.motor.limite
        lista = []
        for est in ESTRATEGIAS:
            av = rapidas.get(est.id)
            lado, cumpridas, total = progresso.melhor_lado(av) if av else (None, 0, 0)
            pct = None
            if prog and prog["id"] == est.id:
                lado, cumpridas, total, pct = prog["dir"], prog["cumpridas"], prog["total"], prog["pct"]
            rec = self.recentes.get(est.id)
            if rec and agora < rec["ate"]:
                estado, lado = "SINAL", rec["dir"]
            elif pct is not None and pct >= limite and lado:
                estado = "FORMANDO"
            elif lado and cumpridas:
                estado = "PARCIAL"
            else:
                estado = "AGUARDANDO"
            lista.append(
                {
                    "id": est.id,
                    "estado": estado,
                    "dir": lado,
                    "cumpridas": cumpridas,
                    "total": total,
                    "pct": pct,
                    "lider": est.id == lider,
                    "em_operacao": est.id in self.operacoes,
                }
            )
        if self.decisao_fixa and agora < self.decisao_fixa["ate"]:
            principal = {k: v for k, v in self.decisao_fixa.items() if k != "ate"}
        else:
            self.decisao_fixa = None
            previa = {k: v["sinal"] for k, v in rapidas.items()}
            formando_lider = (
                {lider: prog["dir"]}
                if (lider and prog and prog["id"] == lider and prog["pct"] >= limite and prog["dir"])
                else {}
            )
            principal = sinal.decidir(self.ranking, previa, formando_lider, self.ativas, previa=True, lider=lider)
        estados = {x["id"]: x for x in lista}
        ver = self._veredito(principal, estados, prog)
        vela = int(formando["epoch"].iat[0]) if len(formando) else self._proximo_fechamento() - self.seg
        await self.enviar(
            "estado",
            estrategias=lista,
            principal=principal,
            veredito=ver,
            limite=limite,
            lider=lider,
            fecha_em=self._proximo_fechamento(),
            agora=self.hub.agora(),
        )
        await self.avisar(self.motor.formacao(ver, prog, vela, self.ativo))

    # ------------------------------------------------------------------ scanner (Top 3)
    def _aberto(self, simbolo: str, s: SerieVelas, fechadas: pd.DataFrame) -> bool:
        if s.mercado_fechado or self.hub.bolsa_aberta(simbolo) is False or not len(fechadas):
            return False
        atraso = self.hub.agora() - (int(fechadas["epoch"].iat[-1]) + self.seg)
        return atraso < ATRASO_MAX_VELAS * self.seg + 5

    @staticmethod
    def _avaliar_ativos(retrato: dict, cfg: ConfigBacktest) -> list[dict]:
        """Nota de cada ativo (roda em thread). `retrato`: {símbolo: (velas fechadas, aberto?)}."""
        return [scanner.avaliar_ativo(sim, df, cfg, aberto) for sim, (df, aberto) in retrato.items()]

    async def _rodar_scanner(self) -> None:
        # o ativo que a pessoa está olhando carrega primeiro; o Top 3 vem depois
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.principal_pronto.wait(), TEMPO_LIMITE_CARGA)
        simbolos = list(dict.fromkeys(ATIVOS_SCANNER))
        series = {sim: await self._obter(sim) for sim in simbolos}
        try:
            await self.hub.ativos()
        except Exception as e:  # noqa: BLE001 - sem a lista o scanner segue (só não sabe se a bolsa abriu)
            log.warning("Lista de ativos indisponível para o scanner: %s", e)
        ultima_chave = None
        while True:
            prontas = {k: s for k, s in series.items() if s.pronta.is_set() and s.velas}
            limite = self.hub.agora() - FOLGA_FECHAMENTO
            ultima_vela = int(limite // self.seg) * self.seg - self.seg
            chave = (ultima_vela, tuple(sorted(prontas)))
            if prontas and chave != ultima_chave:
                ultima_chave = chave
                retrato = {}
                for sim, s in prontas.items():
                    fechadas, _ = self._velas(s)
                    retrato[sim] = (fechadas, self._aberto(sim, s, fechadas))
                resultados = await asyncio.to_thread(self._avaliar_ativos, retrato, self.cfg)
                for sim, s in series.items():
                    if sim not in prontas:
                        motivo = s.erro or "carregando histórico..."
                        resultados.append(
                            {
                                "simbolo": sim,
                                "aberto": None,
                                "pontos": 0,
                                "elegivel": False,
                                "motivo": motivo,
                                "componentes": {},
                                "explicacao": [],
                                "adx": None,
                                "resumo": motivo,
                                "spark": [],
                                "variacao": None,
                            }
                        )
                ordenados = scanner.ordenar(resultados)
                await self.enviar(
                    "top3",
                    itens=[r for r in ordenados if r["elegivel"]][:3],
                    todos=ordenados,
                    regra=scanner.REGRA,
                    timeframe=self.tf,
                    atualizado=time.time(),
                    carregando=len(series) - len(prontas),
                )
            await asyncio.sleep(1)
