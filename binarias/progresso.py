"""Progresso de formação (0 a 100%) de uma estratégia na vela que ainda está se formando.

A vela em formação é tratada como se fechasse no preço atual, e a conta é objetiva:

    progresso = 100 × (PESO × condições cumpridas ÷ total  +  (1 − PESO) × proximidade do gatilho)

* condições: as MESMAS que geram o sinal (estrategias.Condicao), avaliadas na vela atual;
* proximidade = 1 − distância ÷ DIST_MAX, onde distância é quanto o FECHAMENTO da vela atual precisaria
  andar, em ATR (o tamanho típico de uma vela), para todas as condições ficarem cumpridas. A distância é
  achada testando preços (mesmo código do sinal, sem fórmula à parte). Se nem a DIST_MAX ATR o sinal
  sairia (ou se a condição não depende do preço, como horário), a proximidade é 0.

100% = o sinal sairia se a vela fechasse neste preço. Progresso NÃO é probabilidade de acerto.
"""

import math

import pandas as pd

from .config import PROGRESSO_DIST_MAX_ATR, PROGRESSO_PASSO_ATR, PROGRESSO_PESO_CONDICOES
from .estrategias import Estrategia
from .indicadores import atr

EXPLICACAO = (
    f"Como o progresso é calculado: {PROGRESSO_PESO_CONDICOES:.0%} vem das condições da estratégia já "
    f"cumpridas (ex.: 2 de 3) e {1 - PROGRESSO_PESO_CONDICOES:.0%} da proximidade do gatilho: quanto o preço "
    f"precisaria andar, medido em ATR (o tamanho típico de uma vela), para todas as condições valerem. "
    f"A {PROGRESSO_DIST_MAX_ATR:g} ATR ou mais, a proximidade é zero. A vela atual é avaliada como se fechasse "
    "agora. 100% = o sinal sairia se a vela fechasse neste preço. Não é chance de acerto."
)


def pontuar(cumpridas: int, total: int, distancia_atr: float | None) -> int:
    """A fórmula do progresso (0..100). `distancia_atr` None = gatilho fora de alcance."""
    if total <= 0:
        return 0
    frac = cumpridas / total
    if cumpridas == total:
        prox = 1.0
    elif distancia_atr is None:
        prox = 0.0
    else:
        prox = max(0.0, 1.0 - distancia_atr / PROGRESSO_DIST_MAX_ATR)
    return round(100 * (PROGRESSO_PESO_CONDICOES * frac + (1 - PROGRESSO_PESO_CONDICOES) * prox))


def _ultimos(conds, lado: str) -> list[bool]:
    return [bool(getattr(c, lado).iat[-1]) if pd.notna(getattr(c, lado).iat[-1]) else False for c in conds]


def condicoes_agora(est: Estrategia, parcial: pd.DataFrame) -> dict:
    """Avaliação rápida (uma passada): condições na última vela, para os dois lados.
    Devolve {"CALL": [bool...], "PUT": [bool...], "textos": {...}, "sinal": "CALL"|"PUT"|None}."""
    conds = est.gerar_condicoes(parcial)
    call, put = _ultimos(conds, "call"), _ultimos(conds, "put")
    sinal = "CALL" if all(call) and not all(put) else "PUT" if all(put) and not all(call) else None
    return {
        "CALL": call,
        "PUT": put,
        "sinal": sinal,
        "textos": {"CALL": [c.texto_call for c in conds], "PUT": [c.texto_put for c in conds]},
    }


def melhor_lado(av: dict) -> tuple[str | None, int, int]:
    """Lado com mais condições cumpridas (empate = nenhum). Devolve (lado, cumpridas, total)."""
    nc, np_ = sum(av["CALL"]), sum(av["PUT"])
    total = len(av["CALL"])
    if nc == np_:
        return None, nc, total
    return ("CALL", nc, total) if nc > np_ else ("PUT", np_, total)


def _distancia(est: Estrategia, parcial: pd.DataFrame, lado: str, atr_v: float) -> float | None:
    """Menor deslocamento do fechamento atual (em ATR) que cumpre TODAS as condições do lado."""
    if not atr_v or math.isnan(atr_v):
        return None
    df = parcial.copy()
    i = len(df) - 1
    cols = {c: df.columns.get_loc(c) for c in ("high", "low", "close")}
    alta, baixa, fech = (float(df.iat[i, cols[c]]) for c in ("high", "low", "close"))
    passos = round(PROGRESSO_DIST_MAX_ATR / PROGRESSO_PASSO_ATR)
    for k in range(1, passos + 1):
        for direcao in (1, -1):
            novo = fech + direcao * k * PROGRESSO_PASSO_ATR * atr_v
            df.iat[i, cols["close"]] = novo
            df.iat[i, cols["high"]] = max(alta, novo)
            df.iat[i, cols["low"]] = min(baixa, novo)
            if all(_ultimos(est.gerar_condicoes(df), lado.lower())):
                return round(k * PROGRESSO_PASSO_ATR, 2)
    return None


def calcular(est: Estrategia, parcial: pd.DataFrame) -> dict:
    """Progresso completo (com a busca da distância) de `est` em `parcial` (fechadas + vela em formação)."""
    av = condicoes_agora(est, parcial)
    atr_v = float(atr(parcial).iat[-1]) if len(parcial) else float("nan")
    melhor = None
    for lado in ("CALL", "PUT"):
        oks = av[lado]
        cumpridas, total = sum(oks), len(oks)
        dist = 0.0 if cumpridas == total else _distancia(est, parcial, lado, atr_v)
        pct = pontuar(cumpridas, total, dist)
        cand = {
            "dir": lado,
            "pct": pct,
            "cumpridas": cumpridas,
            "total": total,
            "distancia_atr": dist,
            "condicoes": [{"texto": t, "ok": ok} for t, ok in zip(av["textos"][lado], oks, strict=True)],
        }
        if melhor is None or (pct, cumpridas) > (melhor["pct"], melhor["cumpridas"]):
            melhor = cand
    assert melhor is not None
    if melhor["pct"] == 0:
        melhor["dir"] = None
    return {**melhor, "id": est.id, "nome": est.nome, "sinal": av["sinal"], "explicacao": EXPLICACAO}


def montar(
    est: Estrategia, lado: str | None, oks: list[bool], distancia_atr: float | None, textos: list[str] | None = None
) -> dict:
    """Mesmo formato de `calcular`, a partir de condições já conhecidas (usado pela demonstração)."""
    textos = textos or [f"Condição {k + 1}" for k in range(len(oks))]
    pct = pontuar(sum(oks), len(oks), 0.0 if all(oks) else distancia_atr)
    return {
        "id": est.id,
        "nome": est.nome,
        "dir": lado if pct else None,
        "pct": pct,
        "cumpridas": sum(oks),
        "total": len(oks),
        "distancia_atr": distancia_atr,
        "sinal": lado if all(oks) else None,
        "condicoes": [{"texto": t, "ok": ok} for t, ok in zip(textos, oks, strict=True)],
        "explicacao": EXPLICACAO,
    }
