"""Cliente WebSocket da Deriv para scripts (download de histórico).
O modo ao vivo usa o DerivHub (hub.py), que mantém UMA conexão compartilhada."""
import asyncio
import json
import random
import time

import websockets

from .config import INTERVALO_MIN_REQUISICOES, WS_URL
from .log import obter

log = obter("deriv")

# A Deriv aceita count até 5000, mas a API pública nova devolve no máximo ~900 velas por resposta;
# a paginação abaixo cobre qualquer limite.
MAX_POR_REQUISICAO = 5000
ERROS_TEMPORARIOS = {"RateLimit"}


class DerivErro(Exception):
    def __init__(self, mensagem, codigo=None):
        super().__init__(f"[{codigo}] {mensagem}" if codigo else str(mensagem))
        self.codigo = codigo
        self.mensagem = str(mensagem)


class ConexaoPerdida(Exception):
    """A conexão caiu antes da resposta chegar."""


def backoff(tentativa: int, base: float = 1.0, maximo: float = 60.0) -> float:
    """Espera exponencial com jitter: base, 2*base, 4*base... até `maximo`."""
    return min(maximo, base * (2 ** tentativa)) * (0.8 + 0.4 * random.random())


def vela_de_dict(c: dict) -> list:
    """Candle da Deriv (dict com strings ou números) -> [epoch, open, high, low, close]."""
    return [int(c["epoch"]), float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])]


def _bonito(texto: str) -> str:
    return texto.replace("_", " ").title() if texto else "Outros"


def normalizar_ativo(a: dict) -> dict:
    """Aceita tanto o formato novo (underlying_symbol) quanto o antigo (symbol/display_name)."""
    simbolo = a.get("underlying_symbol") or a.get("symbol")
    return {
        "symbol": simbolo,
        "display_name": a.get("underlying_symbol_name") or a.get("display_name") or simbolo,
        "market_display_name": a.get("market_display_name") or _bonito(a.get("market", "")),
        "submarket_display_name": a.get("submarket_display_name") or _bonito(a.get("submarket", "")),
        "exchange_is_open": bool(a.get("exchange_is_open", 0)) and not a.get("is_trading_suspended", 0),
    }


async def baixar_historico(pedir, simbolo: str, gran: int, total: int, agora: float,
                           progresso=None) -> list[list]:
    """Baixa as `total` velas FECHADAS mais recentes, paginando para trás.
    `pedir` é uma corrotina payload -> resposta (DerivClient.pedir ou DerivHub.pedir).
    `agora` deve ser o horário do SERVIDOR (evita incluir a vela em formação se o relógio local adiantar)."""
    velas: list[list] = []
    end = "latest"
    while len(velas) < total:
        falta = total - len(velas) + 1  # +1 compensa a vela em formação
        resp = await pedir({"ticks_history": simbolo, "style": "candles", "granularity": gran,
                            "count": min(falta, MAX_POR_REQUISICAO), "end": end})
        lote = [vela_de_dict(c) for c in resp.get("candles", [])]
        # só velas fechadas e alinhadas à granularidade (já vieram "velas" de 1 tick com epoch
        # desalinhado, ex. 15:19:59 em M5, que deslocam MHI/sequências)
        lote = [v for v in lote if v[0] + gran <= agora and v[0] % gran == 0]
        if velas:
            lote = [v for v in lote if v[0] < velas[0][0]]
        if not lote:
            break  # sem mais histórico disponível
        velas = lote + velas
        end = int(lote[0][0]) - 1
        if progresso:
            progresso(min(len(velas), total), total)
    return velas[-total:]


class DerivClient:
    """Conexão simples para scripts. Reconecta sozinho se a Deriv derrubar a conexão
    (a pública cai a cada ~2 min) e faz backoff exponencial em RateLimit."""

    def __init__(self, url: str = WS_URL, intervalo: float = INTERVALO_MIN_REQUISICOES):
        self.url = url
        self.ws = None
        self.intervalo = intervalo
        self._req_id = 0
        self._ultimo_envio = 0.0
        self.offset = 0.0

    async def _conectar(self):
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.ws = await websockets.connect(self.url, ping_interval=20, max_size=None, open_timeout=20)

    async def __aenter__(self):
        await self._conectar()
        return self

    async def __aexit__(self, *exc):
        if self.ws is not None:
            await self.ws.close()

    async def pedir(self, payload: dict, tentativas: int = 6) -> dict:
        ultimo_erro = None
        for tentativa in range(tentativas):
            espera = self._ultimo_envio + self.intervalo - time.monotonic()
            if espera > 0:
                await asyncio.sleep(espera)
            self._ultimo_envio = time.monotonic()
            self._req_id += 1
            req_id = self._req_id
            try:
                await self.ws.send(json.dumps({**payload, "req_id": req_id}))
                while True:
                    resp = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=60))
                    if resp.get("req_id") == req_id and resp.get("msg_type") != "ohlc":
                        break
            except (websockets.ConnectionClosed, OSError, asyncio.TimeoutError) as e:
                ultimo_erro = e
                espera = backoff(tentativa, 1.0, 30.0)
                log.warning("Conexão com a Deriv perdida (%s). Reconectando em %.1fs...", type(e).__name__, espera)
                await asyncio.sleep(espera)
                try:
                    await self._conectar()
                except Exception as e2:  # tenta de novo na próxima volta
                    ultimo_erro = e2
                continue
            if "error" not in resp:
                return resp
            erro = resp["error"]
            codigo = erro.get("code")
            if codigo in ERROS_TEMPORARIOS and tentativa < tentativas - 1:
                espera = backoff(tentativa, 2.0, 60.0)
                log.warning("Deriv: limite de requisições atingido, aguardando %.1fs...", espera)
                await asyncio.sleep(espera)
                continue
            raise DerivErro(erro.get("message", "Erro desconhecido"), codigo)
        raise DerivErro(f"Falha após {tentativas} tentativas ({ultimo_erro})", "TentativasEsgotadas")

    async def tempo_servidor(self) -> float:
        t0 = time.time()
        r = await self.pedir({"time": 1})
        self.offset = float(r["time"]) - (t0 + time.time()) / 2
        return float(r["time"])

    def agora(self) -> float:
        return time.time() + self.offset

    async def ativos(self) -> list[dict]:
        resp = await self.pedir({"active_symbols": "brief"})
        return [normalizar_ativo(a) for a in resp.get("active_symbols", [])]

    async def velas(self, simbolo: str, gran: int, total: int, progresso=None) -> list[list]:
        await self.tempo_servidor()
        return await baixar_historico(self.pedir, simbolo, gran, total, self.agora(), progresso)
