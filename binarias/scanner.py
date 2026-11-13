"""Top ativos do momento: nota de 0 a 100 com regra explícita (mostrada na tela, item por item).

A nota antiga era em degraus (25/10/0 e 25/12/0) e quase todo ativo "normal" empatava em 50. Agora
cada componente é contínuo e o desempate é declarado:
  * Movimento (até 25): tamanho das velas (percentil do ATR nas últimas 500). Faixa ideal 35–75 = 25;
    cai em linha reta até 0 no percentil 5 e no 100 (mercado parado ou caótico).
  * Tendência (até 25): força pelo ADX, de 0 (ADX ≤ 15) a 25 (ADX ≥ 35). Sem direção clara (lateral)
    vale 40% disso.
  * Estratégia (até 50): só pontua com VANTAGEM COMPROVADA (≥ min_ops e IC 95% acima do break-even):
    30 + até 20 pela folga do limite inferior sobre o break-even (4 pontos por ponto percentual).
  * Desempate: nota com 1 casa, depois maior ADX, depois volatilidade mais perto do meio, depois o nome.
"""

import pandas as pd

from . import backtest as bt
from . import mercado
from . import ranking as rk
from .config import (
    ADX_CHEIO,
    ADX_ZERO,
    FATOR_LATERAL,
    JANELA_RANKING,
    MIN_OPERACOES,
    MIN_VELAS_RANKING,
    MOV_IDEAL,
    MOV_ZERO,
    N_SPARK,
    PONTOS_EST_BASE,
    PONTOS_EST_BONUS,
    PONTOS_MOV,
    PONTOS_TEND,
)
from .log import obter

log = obter("scanner")


REGRA = [
    "Mercado precisa estar ABERTO (fechado = fora do ranking).",
    f"Movimento (até {PONTOS_MOV}): tamanho das velas comparado às últimas 500. Entre o percentil "
    f"{MOV_IDEAL[0]} e {MOV_IDEAL[1]} = {PONTOS_MOV}; cai até 0 no percentil {MOV_ZERO[0]} (parado) "
    f"e {MOV_ZERO[1]} (caótico).",
    f"Tendência (até {PONTOS_TEND}): força pelo ADX, de 0 (ADX ≤ {ADX_ZERO}) a {PONTOS_TEND} "
    f"(ADX ≥ {ADX_CHEIO}); mercado lateral vale {FATOR_LATERAL:.0%} disso.",
    f"Estratégia (até {PONTOS_EST_BASE + PONTOS_EST_BONUS}): só pontua se alguma tiver VANTAGEM COMPROVADA "
    f"(≥ {MIN_OPERACOES} operações e IC 95% acima do break-even): {PONTOS_EST_BASE} + até "
    f"{PONTOS_EST_BONUS} pela folga (4 pontos por ponto percentual).",
    "Desempate: nota com 1 casa decimal; depois maior ADX; depois movimento mais perto do meio; depois o nome.",
]


def pontos_movimento(percentil: float) -> float:
    """Nota de movimento (0..25) pelo percentil do tamanho das velas."""
    if MOV_IDEAL[0] <= percentil <= MOV_IDEAL[1]:
        return float(PONTOS_MOV)
    if percentil < MOV_IDEAL[0]:
        return PONTOS_MOV * max(0.0, (percentil - MOV_ZERO[0]) / (MOV_IDEAL[0] - MOV_ZERO[0]))
    return PONTOS_MOV * max(0.0, (MOV_ZERO[1] - percentil) / (MOV_ZERO[1] - MOV_IDEAL[1]))


def pontos_tendencia(adx: float, tendencia: str) -> float:
    """Nota de tendência (0..25) pela força do ADX; lateral vale menos."""
    base = PONTOS_TEND * min(1.0, max(0.0, (adx - ADX_ZERO) / (ADX_CHEIO - ADX_ZERO)))
    return base if tendencia != "LATERAL" else base * FATOR_LATERAL


def _texto_movimento(p: float) -> str:
    if p < MOV_IDEAL[0]:
        return f"velas pequenas (percentil {p:.0f}): mercado parado"
    if p > MOV_IDEAL[1]:
        return f"velas grandes (percentil {p:.0f}): mercado agitado"
    return f"velas de tamanho normal (percentil {p:.0f})"


def _texto_tendencia(adx: float, tendencia: str) -> str:
    forca = "forte" if adx >= 25 else "média" if adx >= 20 else "fraca"
    if tendencia == "LATERAL":
        return f"sem direção clara (força {forca}, ADX {adx:.0f})"
    return f"{'subindo' if tendencia == 'ALTA' else 'descendo'} com força {forca} (ADX {adx:.0f})"


def pontuar(analise: dict, ranking: dict | None, aberto: bool) -> dict:
    """Nota (0..100, 1 casa) e componentes, com uma frase simples por componente."""
    comp = {"volatilidade": 0.0, "tendencia": 0.0, "estrategia": 0.0}
    vazio = {"pontos": 0.0, "componentes": comp, "explicacao": [], "elegivel": False}
    if not aberto:
        return {**vazio, "motivo": "mercado fechado"}
    if not analise.get("ok"):
        return {**vazio, "motivo": analise.get("motivo", "sem dados")}
    p, adx, tend = analise["atr_percentil"], analise["adx"], analise["tendencia"]
    comp["volatilidade"] = round(pontos_movimento(p), 1)
    comp["tendencia"] = round(pontos_tendencia(adx, tend), 1)
    txt_est = "nenhuma estratégia com vantagem comprovada"
    if ranking and ranking.get("melhor"):
        linha = next(x for x in ranking["linhas"] if x["id"] == ranking["melhor"])
        folga_pp = 100 * (linha["janela"]["ic_inf"] - ranking["break_even"])
        comp["estrategia"] = float(PONTOS_EST_BASE + min(PONTOS_EST_BONUS, max(0, round(4 * folga_pp))))
        folga_txt = f"{folga_pp:.1f}".replace(".", ",")
        txt_est = f"{linha['nome']} comprovada (folga de {folga_txt} p.p. sobre o mínimo)"
    explicacao = [
        {"nome": "Movimento", "pontos": comp["volatilidade"], "max": PONTOS_MOV, "texto": _texto_movimento(p)},
        {"nome": "Tendência", "pontos": comp["tendencia"], "max": PONTOS_TEND, "texto": _texto_tendencia(adx, tend)},
        {
            "nome": "Estratégia",
            "pontos": comp["estrategia"],
            "max": PONTOS_EST_BASE + PONTOS_EST_BONUS,
            "texto": txt_est,
        },
    ]
    return {
        "pontos": round(sum(comp.values()), 1),
        "componentes": comp,
        "explicacao": explicacao,
        "elegivel": True,
        "motivo": "",
    }


def porque(analise: dict, comp: dict, melhor: dict | None) -> str:
    """'Por que está aqui', em uma linha e sem jargão."""
    if melhor:
        return f"Tem estratégia comprovada: {melhor['nome']}"
    if not analise.get("ok"):
        return analise.get("motivo", "sem dados")
    partes = []
    if comp.get("tendencia", 0) >= 10 and analise["tendencia"] != "LATERAL":
        partes.append(
            ("subindo" if analise["tendencia"] == "ALTA" else "descendo")
            + (" com firmeza" if comp["tendencia"] >= 18 else "")
        )
    if comp.get("volatilidade", 0) >= PONTOS_MOV - 0.05:
        partes.append("movimento saudável")
    if not partes:
        return "Sem destaque: mercado lateral ou parado · nenhuma estratégia comprovada"
    texto = " e ".join(partes)
    return texto[0].upper() + texto[1:] + " · nenhuma estratégia comprovada"


def avaliar_ativo(
    simbolo: str,
    df: pd.DataFrame,
    cfg: bt.ConfigBacktest,
    aberto: bool,
    janela: int = JANELA_RANKING,
    min_ops: int = MIN_OPERACOES,
) -> dict:
    """Análise + ranking + nota de UM ativo, usando só as velas FECHADAS desse ativo."""
    try:
        analise = mercado.analisar(df, nome=simbolo.removeprefix("frx"))
        ranking = rk.calcular_ranking(df, cfg, janela, min_ops) if len(df) >= MIN_VELAS_RANKING else None
    except (ValueError, KeyError, IndexError) as e:
        log.exception("Scanner falhou em %s", simbolo)
        analise, ranking = {"ok": False, "motivo": f"erro: {e}"}, None
    return montar_item(simbolo, df, analise, ranking, aberto)


def montar_item(simbolo: str, df: pd.DataFrame, analise: dict, ranking: dict | None, aberto: bool) -> dict:
    """Item do Top 3 (usado pelo ao vivo e pela demonstração). O mini gráfico usa as velas de `df`."""
    pts = pontuar(analise, ranking, aberto)
    melhor = None
    if ranking and ranking["melhor"]:
        linha = next(x for x in ranking["linhas"] if x["id"] == ranking["melhor"])
        melhor = {
            "id": linha["id"],
            "nome": linha["nome"],
            "acerto": linha["janela"]["acerto"],
            "ic_inf": linha["janela"]["ic_inf"],
            "operacoes": linha["janela"]["operacoes"],
        }
    spark = [float(x) for x in df["close"].tail(N_SPARK)] if len(df) else []
    return {
        "simbolo": simbolo,
        "aberto": aberto,
        **pts,
        "tendencia": analise.get("tendencia"),
        "forca": analise.get("forca"),
        "adx": analise.get("adx"),
        "atr_percentil": analise.get("atr_percentil"),
        "volatilidade": analise.get("volatilidade"),
        "melhor_estrategia": melhor,
        "velas": len(df),
        "resumo": analise.get("resumo") or analise.get("motivo"),
        "porque": porque(analise, pts["componentes"], melhor) if pts["elegivel"] else pts["motivo"],
        "spark": spark,
        "variacao": (spark[-1] / spark[0] - 1) if len(spark) > 1 and spark[0] else None,
        "ultima_vela": int(df["epoch"].iat[-1]) if len(df) else None,
    }


def ordenar(resultados: list[dict]) -> list[dict]:
    """Elegíveis primeiro; nota; maior ADX; movimento mais perto do meio (55); nome."""

    def chave(r):
        meio = abs((r.get("atr_percentil") if r.get("atr_percentil") is not None else 55) - 55)
        return (not r["elegivel"], -r["pontos"], -(r.get("adx") or 0), meio, r["simbolo"])

    return sorted(resultados, key=chave)
