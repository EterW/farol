"""DerivHub: UMA conexão WebSocket com a Deriv para o servidor inteiro.

* Requisições com req_id e respostas casadas por Future, com intervalo mínimo entre envios.
* Séries de velas (ativo, granularidade) compartilhadas: cada uma é assinada UMA vez, com contagem
  de referências; quando ninguém mais usa, a assinatura é cancelada (forget) após um tempo.
* A Deriv derruba a conexão pública a cada ~2 min: o hub reconecta na hora, reassina tudo e
  preenche o buraco de velas do período desconectado.
* Backoff exponencial em quedas repetidas e em RateLimit.
* Fila de envio com PRIORIDADE: o ativo que a pessoa está olhando passa na frente do scanner, e um
  download que ninguém mais usa (troca rápida de ativo/tempo gráfico) é cancelado na hora.
"""

import asyncio
import contextlib
import heapq
import json
import time
from typing import Any

import pandas as pd
import websockets

from .config import (
    CONEXAO_ESTAVEL,
    ESPERA_LIBERAR,
    INTERVALO_MANUTENCAO,
    INTERVALO_MIN_REQUISICOES,
    MAX_CONTAGEM_ASSINATURA,
    WS_URL,
)
from .deriv import ConexaoPerdida, DerivErro, backoff, baixar_historico, normalizar_ativo, vela_de_dict
from .log import obter
from .timeframes import COLUNAS

log = obter("hub")


class SerieVelas:
    """Velas base de um ativo, atualizadas ao vivo. `versao` muda a cada alteração."""

    def __init__(self, simbolo: str, gran: int, n_base: int):
        self.simbolo, self.gran, self.n_base = simbolo, gran, n_base
        self.velas: dict[int, list[float]] = {}
        self.versao = 0
        self.casas = 5
        self.sub_id: str | None = None
        self.mercado_fechado = False
        self.erro: str | None = None
        self.pronta = asyncio.Event()
        self.refs = 0
        self.lock = asyncio.Lock()
        self.carregando: asyncio.Task | None = None
        self.liberacao: asyncio.TimerHandle | None = None
        self.refs_prioridade = 0  # consumidores que estão OLHANDO este ativo (passam na frente na fila)
        self.baixadas = 0  # progresso do download inicial (para a tela de carregamento)

    @property
    def prioridade(self) -> bool:
        """Alguém está olhando este ativo agora (não só o scanner)."""
        return self.refs_prioridade > 0

    def mesclar(self, velas) -> None:
        """Acrescenta/atualiza velas, descartando artefatos desalinhados e o excesso antigo."""
        for v in velas:
            if int(v[0]) % self.gran:
                continue  # artefato desalinhado
            self.velas[int(v[0])] = [float(v[1]), float(v[2]), float(v[3]), float(v[4])]
        excesso = len(self.velas) - (self.n_base + 200)
        if excesso > 0:
            for t in sorted(self.velas)[: excesso + 100]:
                del self.velas[t]
        self.versao += 1

    def df(self) -> pd.DataFrame:
        """Velas atuais como DataFrame ordenado."""
        if not self.velas:
            return pd.DataFrame(columns=COLUNAS)
        ts = sorted(self.velas)
        return pd.DataFrame([[t, *self.velas[t]] for t in ts], columns=COLUNAS)

    @property
    def ultima_epoch(self) -> int | None:
        """Abertura da vela mais recente (ou None)."""
        return max(self.velas) if self.velas else None


class DerivHub:
    """Conexão única com a Deriv, compartilhada por todas as abas e pelo scanner."""

    def __init__(self, url: str = WS_URL, intervalo: float = INTERVALO_MIN_REQUISICOES):
        self.url = url
        self.intervalo = intervalo
        self.ws: Any = None
        self._req = 0
        self._pend: dict[int, asyncio.Future] = {}
        self.series: dict[tuple[str, int], SerieVelas] = {}
        self.conectado = asyncio.Event()
        self.offset = 0.0
        self.status: dict[str, Any] = {
            "estado": "desconectado",
            "texto": "Desconectado",
            "desde": time.time(),
            "quedas": 0,
        }
        self._ocupado = False  # vez de enviar (fila com prioridade, ver _vez/_liberar_vez)
        self._fila: list[tuple[int, int, asyncio.Future]] = []
        self._seq_fila = 0
        self._ultimo_envio = 0.0
        self._tarefas: list[asyncio.Task] = []
        self._ativos: dict[str, Any] = {"t": 0.0, "lista": [], "abertos": {}}
        self.conexoes_abertas = 0  # quantas vezes conectou (para testes/diagnóstico)

    # ------------------------------------------------------------------ ciclo de vida
    def iniciar(self) -> None:
        """Começa o laço de conexão e a manutenção (idempotente)."""
        if not self._tarefas:
            self._tarefas = [asyncio.create_task(self._laco()), asyncio.create_task(self._manutencao())]

    async def fechar(self) -> None:
        """Encerra as tarefas e a conexão (desligamento limpo)."""
        for t in self._tarefas:
            t.cancel()
        cargas = [s.carregando for s in self.series.values() if s.carregando and not s.carregando.done()]
        for s in self.series.values():  # downloads em andamento e liberações agendadas também param
            if s.liberacao is not None:
                s.liberacao.cancel()
        for t in cargas:
            t.cancel()
        for t in [*self._tarefas, *cargas]:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tarefas = []
        if self.ws is not None:
            await self.ws.close()

    def agora(self) -> float:
        """Horário do servidor da Deriv."""
        return time.time() + self.offset

    def _set_status(self, estado: str, texto: str) -> None:
        if self.status["estado"] != estado or self.status["texto"] != texto:
            self.status = {**self.status, "estado": estado, "texto": texto, "desde": time.time()}

    async def _laco(self) -> None:
        tentativa = 0
        while True:
            inicio = time.time()
            try:
                self._set_status("conectando", "Conectando na Deriv...")
                async with websockets.connect(self.url, ping_interval=20, max_size=None, open_timeout=15) as ws:
                    self.ws = ws
                    self.conexoes_abertas += 1
                    leitor = asyncio.create_task(self._ler(ws))
                    try:
                        await self._sincronizar_relogio()
                        self.conectado.set()
                        self._set_status("conectado", "Conectado à Deriv")
                        await self._reassinar_todas()
                        await leitor
                    finally:
                        leitor.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - o laço de conexão não pode morrer; tudo vai para o log
                if not isinstance(e, (websockets.ConnectionClosed, ConexaoPerdida)):
                    log.warning("Conexão com a Deriv: %s: %s", type(e).__name__, e)
            finally:
                self.conectado.clear()
                self.ws = None
                self._falhar_pendentes()
                for s in self.series.values():
                    s.sub_id = None
            self.status["quedas"] += 1
            if time.time() - inicio > CONEXAO_ESTAVEL:
                tentativa = 0  # queda normal depois de um tempo conectado: reconecta já
            espera = 0.0 if tentativa == 0 else backoff(tentativa - 1, 2.0, 60.0)
            tentativa += 1
            if espera:
                self._set_status("reconectando", f"Sem conexão com a Deriv. Nova tentativa em {espera:.0f}s...")
                log.warning("Deriv: reconectando em %.1fs (tentativa %d)", espera, tentativa)
                await asyncio.sleep(espera)

    async def _ler(self, ws) -> None:
        try:
            async for bruto in ws:
                try:
                    msg = json.loads(bruto)
                except ValueError:
                    continue
                if msg.get("msg_type") == "ohlc" and "ohlc" in msg:
                    self._ao_ohlc(msg["ohlc"])
                    continue
                fut = self._pend.pop(msg.get("req_id"), None)
                if fut is not None and not fut.done():
                    fut.set_result(msg)
        finally:
            self._falhar_pendentes()

    def _falhar_pendentes(self) -> None:
        pend, self._pend = self._pend, {}
        for f in pend.values():
            if not f.done():
                f.set_exception(ConexaoPerdida())

    def _ao_ohlc(self, o: dict) -> None:
        try:
            s = self.series.get((str(o.get("symbol")), int(o.get("granularity", 0))))
            if s is None:
                return
            s.mesclar([[int(o["open_time"]), o["open"], o["high"], o["low"], o["close"]]])
        except (KeyError, TypeError, ValueError):
            log.warning("Mensagem ohlc inesperada: %s", str(o)[:200])

    # ------------------------------------------------------------------ requisições
    async def _vez(self, prioridade: bool) -> None:
        """Espera a vez de enviar. Pedidos com prioridade passam na frente dos demais (ordem de chegada
        dentro de cada nível)."""
        if not self._ocupado and not self._fila:
            self._ocupado = True
            return
        fut = asyncio.get_running_loop().create_future()
        self._seq_fila += 1
        heapq.heappush(self._fila, (0 if prioridade else 1, self._seq_fila, fut))
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self._liberar_vez()  # recebeu a vez e foi cancelado logo em seguida: passa adiante
            raise

    def _liberar_vez(self) -> None:
        while self._fila:
            _, _, fut = heapq.heappop(self._fila)
            if not fut.done():
                fut.set_result(None)
                return
        self._ocupado = False

    async def _pedir_uma(self, payload: dict, timeout: float, prioridade: bool = False) -> dict:
        await self._vez(prioridade)
        try:
            espera = self._ultimo_envio + self.intervalo - time.monotonic()
            if espera > 0:
                await asyncio.sleep(espera)
            self._ultimo_envio = time.monotonic()
            ws = self.ws
            if ws is None:
                raise ConexaoPerdida()
            self._req += 1
            rid = self._req
            fut = asyncio.get_running_loop().create_future()
            self._pend[rid] = fut
            try:
                await ws.send(json.dumps({**payload, "req_id": rid}))
            except websockets.ConnectionClosed:
                self._pend.pop(rid, None)
                raise ConexaoPerdida() from None
        finally:
            self._liberar_vez()
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pend.pop(rid, None)

    async def pedir(
        self,
        payload: dict,
        tentativas: int = 6,
        timeout: float = 30.0,
        reconectar: bool = True,
        prioridade: bool = False,
    ) -> dict:
        """Envia e espera a resposta. Repete em queda de conexão (se `reconectar`) e em RateLimit."""
        ultimo = None
        for t in range(tentativas):
            if reconectar:
                try:
                    await asyncio.wait_for(self.conectado.wait(), timeout=120)
                except asyncio.TimeoutError:
                    raise DerivErro("Sem conexão com a Deriv", "SemConexao") from None
            try:
                resp = await self._pedir_uma(payload, timeout, prioridade)
            except (ConexaoPerdida, asyncio.TimeoutError) as e:
                if not reconectar:
                    raise ConexaoPerdida() from e
                ultimo = e
                await asyncio.sleep(min(5.0, 0.5 * (t + 1)))
                continue
            if "error" in resp:
                err = resp["error"]
                if err.get("code") == "RateLimit" and t < tentativas - 1:
                    espera = backoff(t, 2.0, 60.0)
                    log.warning("Deriv: limite de requisições, aguardando %.1fs", espera)
                    await asyncio.sleep(espera)
                    continue
                raise DerivErro(err.get("message", "Erro desconhecido"), err.get("code"))
            return resp
        raise DerivErro(f"Falha após {tentativas} tentativas ({type(ultimo).__name__})", "TentativasEsgotadas")

    async def _sincronizar_relogio(self) -> None:
        t0 = time.time()
        r = await self._pedir_uma({"time": 1}, 15)
        if "time" in r:
            self.offset = float(r["time"]) - (t0 + time.time()) / 2

    # ------------------------------------------------------------------ séries
    async def obter_serie(self, simbolo: str, gran: int, n_base: int, prioridade: bool = False) -> SerieVelas:
        """Série compartilhada do ativo; cria e carrega na primeira vez. `prioridade`: é o ativo que a
        pessoa está olhando (os pedidos dele passam na frente dos do scanner)."""
        chave = (simbolo, gran)
        s = self.series.get(chave)
        if s is not None and prioridade:
            s.refs_prioridade += 1
        if s is None:
            s = SerieVelas(simbolo, gran, n_base)
            s.refs_prioridade = int(prioridade)
            self.series[chave] = s
            s.carregando = asyncio.create_task(self._carregar(s))
        elif n_base > s.n_base:
            s.n_base = n_base  # passa a guardar mais; o histórico extra chega no próximo preenchimento
        s.refs += 1
        if s.liberacao is not None:
            s.liberacao.cancel()
            s.liberacao = None
        return s

    def liberar(self, s: SerieVelas, prioridade: bool = False) -> None:
        """Um consumidor a menos; sem consumidores, a assinatura é cancelada depois de um tempo (fica em
        cache para quem voltar ao mesmo ativo). Um download AINDA em andamento é cancelado na hora: numa
        troca rápida de ativo/tempo gráfico ele só atrasaria o ativo novo."""
        s.refs -= 1
        if prioridade:
            s.refs_prioridade = max(0, s.refs_prioridade - 1)
        if s.refs <= 0 and s.carregando is not None and not s.carregando.done():
            asyncio.get_running_loop().create_task(self._remover(s))
            return
        if s.refs <= 0 and s.liberacao is None:
            s.liberacao = asyncio.get_running_loop().call_later(
                ESPERA_LIBERAR, lambda: asyncio.create_task(self._remover(s))
            )

    async def _remover(self, s: SerieVelas) -> None:
        s.liberacao = None
        if s.refs > 0 or self.series.get((s.simbolo, s.gran)) is not s:
            return
        del self.series[(s.simbolo, s.gran)]
        if s.carregando and not s.carregando.done():
            s.carregando.cancel()
        if s.sub_id and self.conectado.is_set():
            # se falhar, a Deriv descarta a assinatura sozinha na próxima queda de conexão
            with contextlib.suppress(DerivErro, ConexaoPerdida, asyncio.TimeoutError):
                await self.pedir({"forget": s.sub_id}, tentativas=1, reconectar=False)

    async def _carregar(self, s: SerieVelas) -> None:
        try:
            await asyncio.wait_for(self.conectado.wait(), timeout=120)

            def ao_progresso(feitas: int, _total: int) -> None:
                s.baixadas = feitas

            velas = await baixar_historico(
                lambda p: self.pedir(p, prioridade=s.prioridade),  # lido a cada página: muda se alguém passar a olhar
                s.simbolo,
                s.gran,
                s.n_base,
                self.agora(),
                ao_progresso,
            )
            s.baixadas = len(velas)
            s.mesclar(velas)
            await self._assinar(s)
            s.erro = None
        except asyncio.CancelledError:
            raise
        except DerivErro as e:
            s.erro = e.mensagem
            log.warning("%s: %s", s.simbolo, e)
        except Exception as e:
            s.erro = f"{type(e).__name__}: {e}"
            log.exception("Falha ao carregar %s", s.simbolo)
        finally:
            s.pronta.set()

    async def _assinar(self, s: SerieVelas, reconectar: bool = True) -> None:
        async with s.lock:
            if s.sub_id:
                return
            ultima = s.ultima_epoch
            if ultima is None:
                contagem = MAX_CONTAGEM_ASSINATURA
            else:
                faltam = int((self.agora() - ultima) // s.gran) + 2
                if faltam > MAX_CONTAGEM_ASSINATURA // 2:
                    # buraco grande (queda longa ou mercado que abriu): pagina o histórico até a última vela
                    velas = await baixar_historico(
                        lambda p: self.pedir(p, reconectar=reconectar, prioridade=s.prioridade),
                        s.simbolo,
                        s.gran,
                        min(faltam, s.n_base),
                        self.agora(),
                    )
                    s.mesclar(velas)
                    faltam = int((self.agora() - (s.ultima_epoch or ultima)) // s.gran) + 2
                contagem = max(2, min(faltam, MAX_CONTAGEM_ASSINATURA))
            try:
                r = await self.pedir(
                    {
                        "ticks_history": s.simbolo,
                        "style": "candles",
                        "granularity": s.gran,
                        "count": contagem,
                        "end": "latest",
                        "subscribe": 1,
                    },
                    reconectar=reconectar,
                    prioridade=s.prioridade,
                )
            except DerivErro as e:
                if e.codigo == "MarketIsClosed":
                    s.mercado_fechado = True
                    return
                raise
            s.mercado_fechado = False
            s.sub_id = (r.get("subscription") or {}).get("id")
            s.casas = int(float(r.get("pip_size") or s.casas))
            s.mesclar([vela_de_dict(c) for c in r.get("candles", [])])

    async def _reassinar_todas(self) -> None:
        for s in list(self.series.values()):
            if s.carregando is None or not s.carregando.done():
                continue  # ainda carregando: ela mesma assina ao terminar
            try:
                await self._assinar(s, reconectar=False)
            except ConexaoPerdida:
                raise
            except DerivErro as e:
                s.erro = e.mensagem
                log.warning("Reassinar %s: %s", s.simbolo, e)

    async def _manutencao(self) -> None:
        while True:
            await asyncio.sleep(INTERVALO_MANUTENCAO)
            if not self.conectado.is_set():
                continue
            for s in list(self.series.values()):
                if s.mercado_fechado and s.carregando and s.carregando.done():
                    try:
                        await self._assinar(s)
                    except (DerivErro, ConexaoPerdida, asyncio.TimeoutError) as e:
                        log.warning("Reabrir %s: %s", s.simbolo, e)
            try:
                await self.ativos(forcar=True)
            except (DerivErro, ConexaoPerdida, asyncio.TimeoutError) as e:
                log.warning("Atualizar lista de ativos: %s", e)

    # ------------------------------------------------------------------ ativos
    async def ativos(self, forcar: bool = False) -> list[dict]:
        """Lista de ativos da Deriv (em cache por 10 minutos)."""
        if forcar or not self._ativos["lista"] or time.time() - self._ativos["t"] > 600:
            r = await self.pedir({"active_symbols": "brief"})
            lista = [normalizar_ativo(a) for a in r.get("active_symbols", [])]
            lista.sort(key=lambda a: (a["market_display_name"], a["submarket_display_name"], a["display_name"]))
            self._ativos = {
                "t": time.time(),
                "lista": lista,
                "abertos": {a["symbol"]: a["exchange_is_open"] for a in lista},
            }
        return self._ativos["lista"]

    def bolsa_aberta(self, simbolo: str) -> bool | None:
        """Segundo a lista de ativos da Deriv (None se ainda não carregada)."""
        return self._ativos["abertos"].get(simbolo) if self._ativos["lista"] else None
