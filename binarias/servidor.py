"""Servidor do modo ao vivo (FastAPI + WebSocket) com UMA conexão compartilhada com a Deriv."""
import argparse
import os
import threading
import webbrowser
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import mercado, scanner
from .config import (ATIVOS_SCANNER, EXPIRACAO_PADRAO, JANELA_RANKING, MIN_OPERACOES, N_HISTORICO,
                     PASTA_STATIC, PAYOUT_PADRAO, TIMEFRAMES_PRONTOS)
from .estrategias import ESTRATEGIAS, EXPLICACAO, POR_ID
from .hub import DerivHub
from .log import configurar_log, obter
from .sessao import CSV_SINAIS, Sessao

log = obter("servidor")
hub = DerivHub()


@asynccontextmanager
async def ciclo(_app):
    hub.iniciar()
    yield
    await hub.fechar()


app = FastAPI(title="Limiar · ao vivo", lifespan=ciclo)
app.mount("/static", StaticFiles(directory=PASTA_STATIC), name="static")


@app.get("/")
async def pagina():
    return FileResponse(os.path.join(PASTA_STATIC, "index.html"))


@app.get("/api/config")
async def api_config():
    return {
        "timeframes": TIMEFRAMES_PRONTOS,
        "csv": CSV_SINAIS,
        "janela": JANELA_RANKING,
        "min_ops": MIN_OPERACOES,
        "n_historico": N_HISTORICO,
        "payout": PAYOUT_PADRAO,
        "expiracao": EXPIRACAO_PADRAO,
        "scanner": ATIVOS_SCANNER,
        "criterio_mercado": mercado.CRITERIO,
        "regra_scanner": scanner.REGRA,
        "estrategias": [{"id": e.id, "nome": e.nome, "descricao": e.descricao, "sigla": e.sigla,
                         "simples": EXPLICACAO.get(e.id, e.descricao),
                         "parametros": e.parametros} for e in ESTRATEGIAS],
    }


@app.get("/api/ativos")
async def api_ativos():
    try:
        return await hub.ativos()
    except Exception as e:
        log.warning("Falha ao listar ativos: %s", e)
        return JSONResponse({"erro": str(e)}, status_code=502)


@app.get("/api/demo/{cenario}")
async def api_demo(cenario: str):
    """Mensagens SIMULADAS de um cenário (a página com ?demo=<cenário> mostra a faixa de demonstração)."""
    from . import demo
    if cenario not in demo.CENARIOS:
        return JSONResponse({"erro": f"use um de: {', '.join(demo.CENARIOS)}"}, status_code=404)
    return demo.mensagens(cenario)


@app.get("/api/status")
async def api_status():
    return {**hub.status, "series": [{"simbolo": s.simbolo, "gran": s.gran, "refs": s.refs, "velas": len(s.velas),
                                      "assinada": bool(s.sub_id), "fechado": s.mercado_fechado, "erro": s.erro}
                                     for s in hub.series.values()]}


@app.websocket("/ws")
async def ws_navegador(ws: WebSocket):
    await ws.accept()
    sessao = Sessao(ws, hub)
    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            if isinstance(msg.get("ativas"), list):
                sessao.ativas = {i for i in msg["ativas"] if i in POR_ID}
            if isinstance(msg.get("observacao"), bool):
                sessao.observacao = msg["observacao"]
            acao = msg.get("acao")
            try:
                if acao == "assinar":
                    payout = float(msg.get("payout", PAYOUT_PADRAO * 100)) / 100
                    await sessao.iniciar(str(msg["simbolo"]).strip(), str(msg["timeframe"]),
                                         int(msg.get("expiracao", 1)), payout)
                elif acao == "parar":
                    await sessao.parar()
                    await sessao.status("Desconectado.")
            except (KeyError, TypeError, ValueError) as e:
                await sessao.status(f"Pedido inválido: {e}", "erro")
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Erro na conexão com o navegador")
    finally:
        sessao.fechado = True
        await sessao.parar()


def main():
    ap = argparse.ArgumentParser(description="Modo ao vivo (site local)")
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--sem-navegador", action="store_true", help="não abrir o navegador automaticamente")
    args = ap.parse_args()

    import uvicorn
    configurar_log()
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.porta}"
    print(f"\nModo ao vivo em {url}  (Ctrl+C para sair)")
    print(f"Sinais registrados em: {CSV_SINAIS}")
    print("Erros registrados em: resultados/erros.log\n")
    if not args.sem_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.porta, log_level="warning")
