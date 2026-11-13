"""Top ativos do momento: pontuação com regra explícita (mostrada na tela)."""
import pandas as pd

from . import backtest as bt, mercado, ranking as rk
from .config import JANELA_RANKING, MIN_OPERACOES
from .log import obter

log = obter("scanner")

PONTOS_VOL, PONTOS_TEND, PONTOS_EST_BASE, PONTOS_EST_BONUS = 25, 25, 30, 20
REGRA = [
    "Mercado precisa estar ABERTO (fechado = fora do ranking).",
    f"Volatilidade (até {PONTOS_VOL}): ATR no percentil 20–90 das últimas 500 velas = {PONTOS_VOL}; "
    f"10–20 ou 90–95 = 10; fora disso = 0.",
    f"Tendência clara (até {PONTOS_TEND}): ALTA/BAIXA com ADX ≥ 25 = {PONTOS_TEND}; com ADX 20–25 = 12; "
    "lateral ou ADX < 20 = 0.",
    f"Estratégias (até {PONTOS_EST_BASE + PONTOS_EST_BONUS}): só pontua se alguma tiver VANTAGEM COMPROVADA "
    f"no ranking (≥ {MIN_OPERACOES} ops na janela e IC 95% acima do break-even): {PONTOS_EST_BASE} + até "
    f"{PONTOS_EST_BONUS} pela folga (4 pontos por ponto percentual do limite inferior acima do break-even).",
    "Empate: maior ADX primeiro.",
]


def pontuar(analise: dict, ranking: dict | None, aberto: bool) -> dict:
    comp = {"volatilidade": 0, "tendencia": 0, "estrategia": 0}
    if not aberto:
        return {"pontos": 0, "componentes": comp, "elegivel": False, "motivo": "mercado fechado"}
    if not analise.get("ok"):
        return {"pontos": 0, "componentes": comp, "elegivel": False, "motivo": analise.get("motivo", "sem dados")}
    p = analise["atr_percentil"]
    if 20 <= p <= 90:
        comp["volatilidade"] = PONTOS_VOL
    elif 10 <= p < 20 or 90 < p <= 95:
        comp["volatilidade"] = 10
    if analise["tendencia"] != "LATERAL":
        if analise["adx"] >= 25:
            comp["tendencia"] = PONTOS_TEND
        elif analise["adx"] >= 20:
            comp["tendencia"] = 12
    if ranking and ranking.get("melhor"):
        linha = next(l for l in ranking["linhas"] if l["id"] == ranking["melhor"])
        folga_pp = 100 * (linha["janela"]["ic_inf"] - ranking["break_even"])
        comp["estrategia"] = PONTOS_EST_BASE + min(PONTOS_EST_BONUS, max(0, round(4 * folga_pp)))
    return {"pontos": sum(comp.values()), "componentes": comp, "elegivel": True, "motivo": ""}


N_SPARK = 48   # fechamentos enviados para o mini gráfico


def porque(analise: dict, comp: dict, melhor: dict | None) -> str:
    """'Por que está aqui', em uma linha e sem jargão."""
    if melhor:
        return f"Tem estratégia comprovada: {melhor['nome']}"
    if not analise.get("ok"):
        return analise.get("motivo", "sem dados")
    partes = []
    if comp.get("tendencia"):
        partes.append(("subindo" if analise["tendencia"] == "ALTA" else "descendo")
                      + (" com firmeza" if comp["tendencia"] >= PONTOS_TEND else ""))
    if comp.get("volatilidade") == PONTOS_VOL:
        partes.append("movimento saudável")
    if not partes:
        return "Sem destaque: mercado lateral ou parado"
    texto = " e ".join(partes)
    return texto[0].upper() + texto[1:] + " · nenhuma estratégia comprovada"


def avaliar_ativo(simbolo: str, df: pd.DataFrame, cfg: bt.ConfigBacktest, aberto: bool,
                  janela: int = JANELA_RANKING, min_ops: int = MIN_OPERACOES) -> dict:
    """Análise + ranking + pontuação de um ativo (velas FECHADAS)."""
    try:
        analise = mercado.analisar(df, nome=simbolo.removeprefix("frx"))
        ranking = rk.calcular_ranking(df, cfg, janela, min_ops) if len(df) >= 60 else None
    except Exception as e:
        log.exception("Scanner falhou em %s", simbolo)
        analise, ranking = {"ok": False, "motivo": f"erro: {e}"}, None
    pts = pontuar(analise, ranking, aberto)
    melhor = None
    if ranking and ranking["melhor"]:
        l = next(x for x in ranking["linhas"] if x["id"] == ranking["melhor"])
        melhor = {"id": l["id"], "nome": l["nome"], "acerto": l["janela"]["acerto"],
                  "ic_inf": l["janela"]["ic_inf"], "operacoes": l["janela"]["operacoes"]}
    return {
        "simbolo": simbolo, "aberto": aberto, **pts,
        "tendencia": analise.get("tendencia"), "forca": analise.get("forca"), "adx": analise.get("adx"),
        "atr_percentil": analise.get("atr_percentil"), "volatilidade": analise.get("volatilidade"),
        "melhor_estrategia": melhor, "velas": int(len(df)),
        "resumo": analise.get("resumo") or analise.get("motivo"),
        "porque": porque(analise, pts["componentes"], melhor) if pts["elegivel"] else pts["motivo"],
        "spark": [float(x) for x in df["close"].tail(N_SPARK)] if len(df) else [],
    }


def ordenar(resultados: list[dict]) -> list[dict]:
    return sorted(resultados, key=lambda r: (not r["elegivel"], -r["pontos"], -(r["adx"] or 0)))
