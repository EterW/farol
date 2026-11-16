"""Servidor do modo ao vivo (FastAPI + WebSocket) com UMA conexão compartilhada com a Deriv."""

import argparse
import asyncio
import os
import re
import threading
import webbrowser
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import assistente, avisos, demo, glossario, mercado, progresso, risco, scanner
from .config import (
    ATIVOS_SCANNER,
    EXPIRACAO_MAX,
    EXPIRACAO_PADRAO,
    HOST_PADRAO,
    JANELA_RANKING,
    MIN_OPERACOES,
    MIN_OPS_AMOSTRA,
    N_HISTORICO,
    PASTA_STATIC,
    PAYOUT_MAX,
    PAYOUT_MIN,
    PAYOUT_PADRAO,
    PORTA_PADRAO,
    PROGRESSO_LIMITE,
    PROGRESSO_LIMITE_MAX,
    PROGRESSO_LIMITE_MIN,
    TIMEFRAME_MAX,
    TIMEFRAMES_PRONTOS,
)
from .estrategias import ESTRATEGIAS, EXPLICACAO
from .hub import DerivHub
from .log import configurar_log, obter
from .sessao import CSV_SINAIS, NavegadorFechado, Sessao
from .timeframes import nome_timeframe, parse_timeframe

log = obter("servidor")
hub = DerivHub()
ajudante = assistente.Assistente()  # desligado sem ANTHROPIC_API_KEY; cache e limite valem para todas as abas

SIMBOLO_VALIDO = re.compile(r"^[A-Za-z0-9_]{1,40}$")
SID_VALIDO = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def validar_assinatura(msg: dict) -> dict:
    """Confere o pedido de assinatura do navegador. Levanta ValueError com mensagem clara."""
    simbolo = str(msg.get("simbolo", "")).strip()
    if not SIMBOLO_VALIDO.match(simbolo):
        raise ValueError("código de ativo inválido (use letras, números e _; ex.: frxEURUSD, R_100)")
    seg = parse_timeframe(str(msg.get("timeframe", "")))
    if seg > TIMEFRAME_MAX:
        raise ValueError("tempo gráfico máximo é D1")
    try:
        expiracao = int(msg.get("expiracao", EXPIRACAO_PADRAO))
        payout = float(msg.get("payout", PAYOUT_PADRAO * 100))
    except (TypeError, ValueError):
        raise ValueError("expiração e payout precisam ser números") from None
    if not 1 <= expiracao <= EXPIRACAO_MAX:
        raise ValueError(f"expiração deve ficar entre 1 e {EXPIRACAO_MAX} velas")
    if not PAYOUT_MIN <= payout <= PAYOUT_MAX:
        raise ValueError(f"payout deve ficar entre {PAYOUT_MIN:.0f}% e {PAYOUT_MAX:.0f}%")
    sid = msg.get("sid")
    sid = str(sid) if sid is not None and SID_VALIDO.match(str(sid)) else None
    return {
        "simbolo": simbolo,
        "timeframe": nome_timeframe(seg),
        "expiracao": expiracao,
        "payout": payout / 100,
        "sid": sid,
    }


@asynccontextmanager
async def ciclo(_app):
    """Liga a conexão com a Deriv ao subir o servidor e a desliga ao encerrar."""
    hub.iniciar()
    yield
    await hub.fechar()


app = FastAPI(title="Farol · ao vivo", lifespan=ciclo)
app.mount("/static", StaticFiles(directory=PASTA_STATIC), name="static")


@app.get("/")
async def pagina():
    """Página principal."""
    return FileResponse(os.path.join(PASTA_STATIC, "index.html"))


@app.get("/como-decide")
async def pagina_como_decide():
    """Página educativa: o fluxo dados -> estratégias -> ranking com margem de erro -> validação -> sinal."""
    return FileResponse(os.path.join(PASTA_STATIC, "como-decide.html"))


@app.get("/api/glossario")
async def api_glossario():
    """Glossário curto e o mini-tour 'Por que o Farol fica em silêncio'."""
    return {"termos": glossario.GLOSSARIO, "silencio": glossario.SILENCIO}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Ícone da aba do navegador."""
    return FileResponse(os.path.join(PASTA_STATIC, "marca", "favicon.ico"))


@app.get("/api/config")
async def api_config():
    """Configuração e textos de regra usados pela página."""
    return {
        "timeframes": TIMEFRAMES_PRONTOS,
        "csv": CSV_SINAIS,
        "janela": JANELA_RANKING,
        "min_ops": MIN_OPERACOES,
        "min_ops_amostra": MIN_OPS_AMOSTRA,
        "limite_formacao": PROGRESSO_LIMITE,
        "limite_formacao_faixa": [PROGRESSO_LIMITE_MIN, PROGRESSO_LIMITE_MAX],
        "explicacao_progresso": progresso.EXPLICACAO,
        "n_historico": N_HISTORICO,
        "payout": PAYOUT_PADRAO,
        "expiracao": EXPIRACAO_PADRAO,
        "scanner": ATIVOS_SCANNER,
        "criterio_mercado": mercado.CRITERIO,
        "regra_scanner": scanner.REGRA,
        "assistente": ajudante.status(),
        "estrategias": [
            {
                "id": e.id,
                "nome": e.nome,
                "descricao": e.descricao,
                "sigla": e.sigla,
                "simples": EXPLICACAO.get(e.id, e.descricao),
                "parametros": e.parametros,
            }
            for e in ESTRATEGIAS
        ],
    }


@app.get("/api/ativos")
async def api_ativos():
    """Ativos disponíveis na Deriv."""
    try:
        return await hub.ativos()
    except Exception as e:  # noqa: BLE001 - qualquer falha vira 502 com a mensagem, e fica no log
        log.warning("Falha ao listar ativos: %s", e)
        return JSONResponse({"erro": str(e)}, status_code=502)


@app.get("/api/demo/{cenario}")
async def api_demo(cenario: str):
    """Mensagens SIMULADAS de um cenário (a página com ?demo=<cenário> mostra a faixa de demonstração)."""
    if cenario not in demo.CENARIOS:
        return JSONResponse({"erro": f"use um de: {', '.join(demo.CENARIOS)}"}, status_code=404)
    return demo.mensagens(cenario)


@app.get("/api/avisos/teste")
async def api_avisos_teste():
    """Os tipos de aviso com os textos reais (botão "Testar alertas")."""
    return avisos.exemplos()


@app.get("/api/assistente")
async def api_assistente():
    """Estado do assistente (ligado/desligado, modelo, chamadas restantes, aviso de privacidade). Nunca a chave."""
    return ajudante.status()


async def explicar(sessao: Sessao, pergunta: str) -> None:
    """Pedido "Explique para mim" / pergunta livre (a aba pode ter fechado no meio: ignora)."""
    try:
        await _explicar(sessao, pergunta)
    except NavegadorFechado:
        pass
    except Exception:
        log.exception("Erro no assistente")


async def _explicar(sessao: Sessao, pergunta: str) -> None:
    """O JSON vem do estado da sessão (dados já calculados), nunca do navegador."""
    pacote = sessao.dados_assistente()
    if pacote is None:
        await sessao.enviar(
            "assistente",
            fonte="sem_dados",
            texto="Conecte um ativo e espere o ranking ficar pronto.",
            aviso=assistente.AVISO_SEM_IA,
            pergunta=pergunta,
            status=ajudante.status(),
        )
        return
    dados, chave = pacote
    try:
        resultado = await asyncio.wait_for(
            asyncio.to_thread(ajudante.explicar, dados, chave, pergunta), ajudante.config.tempo_limite + 5
        )
    except TimeoutError:
        resultado = {
            "fonte": "erro",
            "texto": assistente.texto_padrao(dados),
            "aviso": assistente.AVISO_SEM_IA,
            "motivo": "O assistente demorou demais.",
            "pergunta": pergunta,
        }
    await sessao.enviar("assistente", **resultado, status=ajudante.status())


async def _corpo(req: Request) -> dict:
    try:
        corpo = await req.json()
    except ValueError:
        raise ValueError("corpo não é JSON") from None
    if not isinstance(corpo, dict):
        raise ValueError("corpo deve ser um objeto JSON")
    return corpo


@app.post("/api/risco/dia")
async def api_risco_dia(req: Request):
    """'Minha banca': situação do dia (resultado, distância até o limite, bloqueio). Nada é gravado."""
    try:
        c = await _corpo(req)
        ops = c.get("operacoes") or []
        if not isinstance(ops, list) or len(ops) > 2000:
            raise ValueError("operacoes deve ser uma lista (até 2000)")
        entrada = risco.valor_entrada(c.get("banca", 0), c.get("pct", 1))
        dia = risco.estado_dia(
            c.get("banca_inicio", c.get("banca", 0)),
            [o for o in ops if isinstance(o, dict)],
            c.get("perda_max_pct", risco.PERDA_DIA_PADRAO),
            c.get("parar_apos", risco.PARAR_APOS_PADRAO),
            c.get("meta_pct"),
        )
        return {"entrada": entrada, "dia": dia}
    except ValueError as e:
        return JSONResponse({"erro": str(e)}, status_code=400)


@app.post("/api/risco/simular")
async def api_risco_simular(req: Request):
    """Simulador 'e se' (Monte Carlo, entrada fixa, sem martingale)."""
    try:
        c = await _corpo(req)
        return await asyncio.to_thread(
            risco.simular,
            c.get("acerto"),
            c.get("payout", PAYOUT_PADRAO),
            c.get("pct", 1),
            c.get("n_operacoes", 100),
            c.get("simulacoes", 5000),
            c.get("limite_ruina_pct", 50),
        )
    except ValueError as e:
        return JSONResponse({"erro": str(e)}, status_code=400)


@app.get("/api/status")
async def api_status():
    """Diagnóstico da conexão e das séries assinadas."""
    return {
        **hub.status,
        "series": [
            {
                "simbolo": s.simbolo,
                "gran": s.gran,
                "refs": s.refs,
                "velas": len(s.velas),
                "assinada": bool(s.sub_id),
                "fechado": s.mercado_fechado,
                "erro": s.erro,
            }
            for s in hub.series.values()
        ],
    }


@app.websocket("/ws")
async def ws_navegador(ws: WebSocket):
    """Canal ao vivo com uma aba: recebe pedidos validados e envia velas, veredito e avisos."""
    await ws.accept()
    sessao = Sessao(ws, hub)
    tarefas_ia: set[asyncio.Task] = set()
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                await sessao.status("Mensagem inválida recebida (não é JSON).", "erro")
                continue
            if not isinstance(msg, dict):
                continue
            await sessao.configurar(msg)
            acao = msg.get("acao")
            if acao == "assinar":
                try:
                    pedido = validar_assinatura(msg)
                except ValueError as e:
                    await sessao.status(f"Pedido inválido: {e}", "erro")
                    continue
                await sessao.iniciar(**pedido)
            elif acao == "explicar":
                pergunta = msg.get("pergunta")
                tarefa = asyncio.create_task(explicar(sessao, pergunta if isinstance(pergunta, str) else ""))
                tarefas_ia.add(tarefa)  # referência guardada até terminar (não bloqueia o canal ao vivo)
                tarefa.add_done_callback(tarefas_ia.discard)
            elif acao == "parar":
                await sessao.parar()
                await sessao.status("Desconectado.")
    except (WebSocketDisconnect, NavegadorFechado):
        pass
    except Exception:
        log.exception("Erro na conexão com o navegador")
    finally:
        sessao.fechado = True
        await sessao.parar()


def main() -> None:
    """Ponto de entrada (python live.py): sobe o site local e abre o navegador."""
    ap = argparse.ArgumentParser(description="Farol · modo ao vivo (site local)")
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    ap.add_argument("--host", default=HOST_PADRAO, help="padrão 127.0.0.1 (só esta máquina)")
    ap.add_argument("--sem-navegador", action="store_true", help="não abrir o navegador automaticamente")
    args = ap.parse_args()

    import uvicorn

    configurar_log()
    local = args.host in ("127.0.0.1", "localhost", "::1")
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.porta}"
    print(f"\nFarol · sinais com evidência estatística, sem promessa\nAberto em {url}  (Ctrl+C para sair)")
    if not local:
        print(f"ATENÇÃO: host {args.host} deixa o Farol acessível por outras máquinas da rede (não há senha).")
        log.warning("Servidor exposto fora de 127.0.0.1 (host=%s)", args.host)
    print(f"Sinais registrados em: {CSV_SINAIS}")
    print("Erros registrados em: resultados/erros.log\n")
    if not args.sem_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(app, host=args.host, port=args.porta, log_level="warning")
    except OSError as e:  # ex.: porta em uso
        log.error("Não foi possível abrir a porta %s: %s", args.porta, e)
        print(f"Não foi possível abrir a porta {args.porta} ({e}). Tente: python live.py --porta 8080")
        raise SystemExit(1) from None
    print("Farol encerrado.")
