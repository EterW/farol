"""Servidor Deriv falso (local) para testar o hub sem internet.
Imita o que a API pública real faz: máx. 900 velas por resposta, ohlc com symbol/granularity,
MarketIsClosed para ativos fechados, RateLimit e quedas de conexão."""
import asyncio
import json
import math
import time

import websockets

MAX_RESPOSTA = 900


def preco(simbolo: str, epoch: int) -> float:
    return 100 + math.sin(epoch / 3000 + len(simbolo)) * 2 + (epoch % 7) * 0.01


class FakeDeriv:
    def __init__(self, fechados=(), rate_limit_primeiros=0, derrubar_apos=None):
        self.fechados = set(fechados)
        self.rate_limit_restantes = rate_limit_primeiros
        self.derrubar_apos = derrubar_apos       # s após conectar: derruba a 1ª conexão
        self.conexoes = 0
        self.pedidos: list[dict] = []
        self.server = None
        self.porta = None

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.porta}"

    def contar(self, **filtro) -> int:
        return sum(all(p.get(k) == v for k, v in filtro.items()) for p in self.pedidos)

    async def __aenter__(self):
        self.server = await websockets.serve(self._handler, "127.0.0.1", 0)
        self.porta = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()

    def _velas(self, simbolo, gran, count, end):
        agora = int(time.time())
        fim = agora if end == "latest" else int(end)
        ultima = fim - fim % gran
        epochs = [ultima - gran * k for k in range(min(count, MAX_RESPOSTA))][::-1]
        return [{"epoch": e, "open": preco(simbolo, e), "high": preco(simbolo, e) + 0.05,
                 "low": preco(simbolo, e) - 0.05, "close": preco(simbolo, e + gran // 2)} for e in epochs]

    async def _handler(self, ws):
        self.conexoes += 1
        numero = self.conexoes
        assinaturas: dict[str, tuple] = {}
        envio = asyncio.Lock()

        async def enviar(m):
            async with envio:
                await ws.send(json.dumps(m))

        async def stream():
            while True:
                await asyncio.sleep(0.1)
                agora = int(time.time())
                for sid, (sim, gran, rid) in list(assinaturas.items()):
                    ot = agora - agora % gran
                    await enviar({"msg_type": "ohlc", "req_id": rid, "subscription": {"id": sid},
                                  "ohlc": {"symbol": sim, "granularity": gran, "open_time": ot, "epoch": agora,
                                           "open": str(preco(sim, ot)), "high": str(preco(sim, ot) + 0.05),
                                           "low": str(preco(sim, ot) - 0.05), "close": str(preco(sim, agora))}})

        async def derrubar():
            await asyncio.sleep(self.derrubar_apos)
            await ws.close()

        tarefas = [asyncio.create_task(stream())]
        if self.derrubar_apos and numero == 1:
            tarefas.append(asyncio.create_task(derrubar()))
        try:
            async for bruto in ws:
                req = json.loads(bruto)
                self.pedidos.append(req)
                rid = req.get("req_id")
                base = {"echo_req": req, "req_id": rid}
                if "time" in req:
                    await enviar({**base, "msg_type": "time", "time": int(time.time())})
                elif "active_symbols" in req:
                    await enviar({**base, "msg_type": "active_symbols", "active_symbols": [
                        {"underlying_symbol": "frxEURUSD", "underlying_symbol_name": "EUR/USD", "market": "forex",
                         "submarket": "major_pairs", "exchange_is_open": 1},
                        {"underlying_symbol": "frxFECHADO", "underlying_symbol_name": "Fechado", "market": "forex",
                         "submarket": "major_pairs", "exchange_is_open": 0}]})
                elif "forget" in req:
                    assinaturas.pop(req["forget"], None)
                    await enviar({**base, "msg_type": "forget", "forget": 1})
                elif "ticks_history" in req:
                    sim, gran = req["ticks_history"], int(req["granularity"])
                    if self.rate_limit_restantes > 0:
                        self.rate_limit_restantes -= 1
                        await enviar({**base, "msg_type": "candles",
                                      "error": {"code": "RateLimit", "message": "Limite"}})
                        continue
                    if req.get("subscribe") and sim in self.fechados:
                        await enviar({**base, "msg_type": "candles",
                                      "error": {"code": "MarketIsClosed", "message": "Mercado fechado."}})
                        continue
                    resp = {**base, "msg_type": "candles", "pip_size": 5,
                            "candles": self._velas(sim, gran, int(req.get("count", 500)), req.get("end", "latest"))}
                    if req.get("subscribe"):
                        sid = f"sub-{numero}-{len(assinaturas)}-{sim}"
                        assinaturas[sid] = (sim, gran, rid)
                        resp["subscription"] = {"id": sid}
                    await enviar(resp)
        except websockets.ConnectionClosed:
            pass
        finally:
            for t in tarefas:
                t.cancel()
