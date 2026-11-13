"""Sessão ao vivo (uma por aba do navegador). Usa o DerivHub compartilhado e exatamente o mesmo
código do backtest: estrategias.gerar_sinais, backtest.executar/resolver (via ranking) e
timeframes.agregar."""
import asyncio
import csv
import json
import os
import time
from datetime import datetime, timezone

import pandas as pd

from . import mercado, scanner, sinal, veredito
from .backtest import ConfigBacktest, resolver
from .config import (ATIVOS_SCANNER, EMPATE_PADRAO, FOLGA_FECHAMENTO, JANELA_RANKING, MIN_OPERACOES,
                     N_HISTORICO, N_VELAS_GRAFICO, N_VELAS_PREVIA, PASTA_RESULTADOS)
from .estrategias import ESTRATEGIAS, POR_ID, ultimo_valor
from .hub import DerivHub, SerieVelas
from .log import obter
from .ranking import calcular_ranking
from .timeframes import agregar, granularidade_base, nome_timeframe, parse_timeframe

log = obter("sessao")

CSV_SINAIS = os.path.join(PASTA_RESULTADOS, "sinais_ao_vivo.csv")
COLUNAS_CSV = ["data_sinal", "data_entrada", "ativo", "timeframe", "estrategia", "principal", "direcao",
               "expiracao", "preco_entrada", "preco_saida", "resultado"]


class NavegadorFechado(Exception):
    pass


def fmt_data(epoch: int) -> str:
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


def _linhas(df: pd.DataFrame) -> list[list]:
    return [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])]
            for r in df[["epoch", "open", "high", "low", "close"]].itertuples(index=False)]


class Sessao:
    def __init__(self, navegador, hub: DerivHub):
        self.nav = navegador
        self.hub = hub
        self.tarefas: list[asyncio.Task] = []
        self.series: list[SerieVelas] = []
        self.ativas: set[str] = set(POR_ID)
        self.observacao = False          # modo observação (só muda o que a tela mostra, nunca o ENTRAR)
        self.analise: dict | None = None
        self.operacoes: dict[str, dict] = {}
        self._seq = 0
        self._lock_envio = asyncio.Lock()
        self.fechado = False
        self.simbolo = self.tf = None

    # ------------------------------------------------------------------ envio
    async def enviar(self, tipo: str, **conteudo) -> None:
        if self.fechado:
            raise NavegadorFechado()
        try:
            async with self._lock_envio:
                await self.nav.send_text(json.dumps(_limpar({"tipo": tipo, **conteudo}), default=str))
        except Exception as e:
            self.fechado = True
            raise NavegadorFechado() from e

    async def status(self, texto: str, nivel: str = "info") -> None:
        await self.enviar("status", texto=texto, nivel=nivel)

    # ------------------------------------------------------------------ controle
    async def iniciar(self, simbolo: str, timeframe: str, expiracao: int, payout: float) -> None:
        await self.parar()
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
        self.hold = min(60.0, max(10.0, seg * 0.25))   # quanto tempo mostrar ENTRAR AGORA / CONFLITO
        self.ranking = None
        self.preparo: dict[str, str | None] = {}
        self.recentes: dict[str, dict] = {}
        self.decisao_fixa: dict | None = None
        self.tarefas = [asyncio.create_task(self._proteger(c, nome)) for c, nome in (
            (self._rodar(), "ativo"), (self._rodar_scanner(), "scanner"), (self._vigiar_conexao(), "conexão"))]

    async def parar(self) -> None:
        for t in self.tarefas:
            t.cancel()
        for t in self.tarefas:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self.tarefas = []
        for s in self.series:
            self.hub.liberar(s)
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
            try:
                await self.status(f"Erro interno ({nome}): {e}. Detalhes em resultados/erros.log", "erro")
            except NavegadorFechado:
                pass

    async def _obter(self, simbolo: str) -> SerieVelas:
        s = await self.hub.obter_serie(simbolo, self.gran, self.n_base)
        self.series.append(s)
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
    async def _rodar(self) -> None:
        await self.status(f"Carregando {N_HISTORICO} velas de {self.simbolo} {self.tf}...")
        s = await self._obter(self.simbolo)
        await s.pronta.wait()
        if not s.velas:
            await self.status(f"Deriv: {s.erro or 'nenhuma vela retornada'} ({self.simbolo})", "erro")
            return
        self.serie = s
        self.df, formando = self._velas(s)
        if len(self.df) < 2:
            await self.status("Histórico insuficiente para este ativo/timeframe.", "erro")
            return
        self.ultima_fechada = int(self.df["epoch"].iat[-1])
        await self._inicializar(formando)
        if s.mercado_fechado:
            await self.status(f"Mercado fechado: mostrando só o histórico de {self.simbolo} {self.tf}.", "aviso")
        else:
            await self.status(f"Ao vivo: {self.simbolo} {self.tf}", "ok")

        versao, ultima_formando, ultimo_estado, ultimo_calc = -1, None, 0.0, 0.0
        while True:
            await asyncio.sleep(0.25)
            if s.versao == versao and time.time() - ultimo_calc < 1:
                continue
            versao, ultimo_calc = s.versao, time.time()
            fechadas, formando = self._velas(s)
            if len(fechadas) and int(fechadas["epoch"].iat[-1]) > self.ultima_fechada:
                novas = fechadas[fechadas["epoch"] > self.ultima_fechada]
                self.ultima_fechada = int(fechadas["epoch"].iat[-1])
                self.df = fechadas
                for v in _linhas(novas):
                    await self.enviar("vela", v=v)
                await self._ao_fechar(formando, len(novas))
                ultimo_estado = 0.0
            atual = _linhas(formando)[0] if len(formando) else None
            if atual and atual != ultima_formando:
                ultima_formando = atual
                await self.enviar("vela", v=atual)
            if time.time() - ultimo_estado >= 1:
                ultimo_estado = time.time()
                await self._enviar_estado(formando)

    def _calcular(self, df: pd.DataFrame, formando: pd.DataFrame, ativas: set) -> tuple[dict, dict]:
        r = calcular_ranking(df, self.cfg, JANELA_RANKING, MIN_OPERACOES, elegiveis=ativas)
        a = mercado.analisar(df, formando, nome=f"{self.simbolo.removeprefix('frx')} {self.tf}")
        return r, a

    async def _inicializar(self, formando: pd.DataFrame) -> None:
        df = self.df
        ranking, analise = await asyncio.to_thread(self._calcular, df, formando, set(self.ativas))
        self.ranking, self.analise = ranking, analise
        self.preparo = {l["id"]: l["preparo"] for l in ranking["linhas"]}
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
        velas = _linhas(grafico) + _linhas(formando)
        await self.enviar("historico", simbolo=self.simbolo, timeframe=self.tf, seg=self.seg,
                          expiracao=self.cfg.expiracao, payout=self.cfg.payout, casas=self.serie.casas,
                          janela_entrada=self.hold,
                          velas=velas, sinais=marcas, n_velas=len(df))
        await self._enviar_analise(ranking, analise)
        dec = sinal.decidir(ranking, {}, self.preparo, self.ativas)
        estados = {k: {"estado": "SE PREPARANDO", "dir": v} for k, v in self.preparo.items() if v}
        await self.enviar("decisao", **dec, novo=False, t=self.ultima_fechada, veredito=self._veredito(dec, estados))

    def _veredito(self, dec: dict, estados: dict) -> dict:
        humano = (self.analise or {}).get("humano")
        return veredito.montar(dec, self.ranking, humano, self.observacao, estados, self.ativas)

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
                await self.enviar("resultado", op=op["n"], id=est_id, resultado=res, entrada=entrada, saida=saida)

        # 2) ranking + análise na vela que acabou de fechar (em thread: não trava o servidor)
        ativas = set(self.ativas)
        ranking, analise = await asyncio.to_thread(self._calcular, df, formando, ativas)
        self.ranking, self.analise = ranking, analise
        sinais = {l["id"]: l["sinal"] for l in ranking["linhas"]}
        self.preparo = {l["id"]: l["preparo"] for l in ranking["linhas"]}
        dec = sinal.decidir(ranking, sinais, self.preparo, ativas)
        t = int(epochs[-1])
        if n_novas > 1:
            log.warning("%s %s: %d velas fecharam de uma vez (queda/atraso); só a última foi avaliada",
                        self.simbolo, self.tf, n_novas)

        # 3) registra os sinais das estratégias marcadas (teste ao vivo) — uma operação por estratégia
        for est_id, d in sinais.items():
            if not d:
                continue
            nome = POR_ID[est_id].nome
            registrado = est_id in ativas and est_id not in self.operacoes
            principal = dec["estado"] == "ENTRAR" and est_id == dec["estrategia"]
            if registrado:
                self._seq += 1
                self.operacoes[est_id] = {"n": self._seq, "id": est_id, "nome": nome, "dir": d, "t": t,
                                          "t_entrada": t + self.seg, "principal": principal}
                self.recentes[est_id] = {"dir": d, "ate": time.time() + self.hold}
            await self.enviar("sinal", op=self._seq if registrado else None, id=est_id, nome=nome, dir=d, t=t,
                              registrado=registrado, principal=principal, ativo=self.simbolo)

        # 4) decisão principal (fica fixa por alguns segundos se for ENTRAR/CONFLITO)
        self.decisao_fixa = {**dec, "ate": time.time() + self.hold} if dec["estado"] in ("ENTRAR", "CONFLITO") else None
        await self._enviar_analise(ranking, analise)
        estados = {k: {"estado": "SINAL", "dir": v} for k, v in sinais.items() if v}
        await self.enviar("decisao", **dec, novo=True, t=t, veredito=self._veredito(dec, estados))

    def _registrar(self, op: dict, entrada, saida, resultado: str) -> None:
        try:
            gravar_csv({
                "data_sinal": fmt_data(op["t"]), "data_entrada": fmt_data(op["t_entrada"]),
                "ativo": self.simbolo, "timeframe": self.tf, "estrategia": op["nome"],
                "principal": "sim" if op.get("principal") else "não", "direcao": op["dir"],
                "expiracao": self.cfg.expiracao,
                "preco_entrada": "" if entrada is None else entrada,
                "preco_saida": "" if saida is None else saida, "resultado": resultado,
            })
        except OSError:
            log.exception("Não foi possível gravar %s (arquivo aberto no Excel?)", CSV_SINAIS)

    def _previa(self, formando: pd.DataFrame) -> dict:
        """O sinal já estaria valendo se a vela em formação fechasse agora? (só para SE PREPARANDO)"""
        if not len(formando) or not len(self.df):
            return {}
        parcial = pd.concat([self.df.tail(N_VELAS_PREVIA), formando], ignore_index=True)
        saida = {}
        for est in ESTRATEGIAS:
            try:
                saida[est.id] = ultimo_valor(est.gerar_sinais(parcial))
            except Exception:
                saida[est.id] = None
        return saida

    async def _enviar_estado(self, formando: pd.DataFrame) -> None:
        if self.ranking is None:
            return
        previa = await asyncio.to_thread(self._previa, formando)
        agora = time.time()
        lista = []
        for est in ESTRATEGIAS:
            rec = self.recentes.get(est.id)
            if rec and agora < rec["ate"]:
                estado, direcao = "SINAL", rec["dir"]
            else:
                direcao = previa.get(est.id) or self.preparo.get(est.id)
                estado = "SE PREPARANDO" if direcao else "AGUARDANDO"
            lista.append({"id": est.id, "estado": estado, "dir": direcao, "em_operacao": est.id in self.operacoes})
        if self.decisao_fixa and agora < self.decisao_fixa["ate"]:
            principal = {k: v for k, v in self.decisao_fixa.items() if k != "ate"}
        else:
            self.decisao_fixa = None
            principal = sinal.decidir(self.ranking, previa, self.preparo, self.ativas, previa=True)
        estados = {x["id"]: x for x in lista}
        await self.enviar("estado", estrategias=lista, principal=principal,
                          veredito=self._veredito(principal, estados),
                          fecha_em=self._proximo_fechamento(), agora=self.hub.agora())

    # ------------------------------------------------------------------ scanner (Top 3)
    def _aberto(self, simbolo: str, s: SerieVelas, fechadas: pd.DataFrame) -> bool:
        if s.mercado_fechado or self.hub.bolsa_aberta(simbolo) is False or not len(fechadas):
            return False
        atraso = self.hub.agora() - (int(fechadas["epoch"].iat[-1]) + self.seg)
        return atraso < 3 * self.seg + 5

    async def _rodar_scanner(self) -> None:
        simbolos = list(dict.fromkeys(ATIVOS_SCANNER))
        series = {sim: await self._obter(sim) for sim in simbolos}
        try:
            await self.hub.ativos()
        except Exception as e:
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
                cfg = self.cfg
                resultados = await asyncio.to_thread(
                    lambda: [scanner.avaliar_ativo(sim, df, cfg, ab) for sim, (df, ab) in retrato.items()])
                for sim, s in series.items():
                    if sim not in prontas:
                        motivo = s.erro or "carregando histórico..."
                        resultados.append({"simbolo": sim, "aberto": None, "pontos": 0, "elegivel": False,
                                           "motivo": motivo, "componentes": {}, "adx": None, "resumo": motivo})
                ordenados = scanner.ordenar(resultados)
                await self.enviar("top3", itens=[r for r in ordenados if r["elegivel"]][:3], todos=ordenados,
                                  regra=scanner.REGRA, timeframe=self.tf, atualizado=time.time(),
                                  carregando=len(series) - len(prontas))
            await asyncio.sleep(1)
