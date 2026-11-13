"""Estatística usada no ranking e na validação."""

import math
from statistics import NormalDist

from .config import CONFIANCA


def z_bilateral(confianca: float = CONFIANCA) -> float:
    """Valor z bilateral para o nível de confiança (0,95 -> 1,96)."""
    return NormalDist().inv_cdf((1 + confianca) / 2)


def wilson(acertos: int, n: int, confianca: float = CONFIANCA) -> tuple[float, float]:
    """Intervalo de confiança de Wilson para uma proporção (0..1). n = 0 -> (0, 1)."""
    if n <= 0:
        return 0.0, 1.0
    z = z_bilateral(confianca)
    p = acertos / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    meia = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - meia), min(1.0, centro + meia)


def break_even(payout: float) -> float:
    """Taxa de acerto mínima para não perder dinheiro sem gale: p*payout = (1-p) -> p = 1/(1+payout)."""
    return 1.0 / (1.0 + payout)


def z_duas_proporcoes(w1: int, n1: int, w2: int, n2: int) -> float | None:
    """Estatística z da diferença (p1 - p2) com variância combinada. None se não der para calcular."""
    if n1 <= 0 or n2 <= 0:
        return None
    p = (w1 + w2) / (n1 + n2)
    var = p * (1 - p) * (1 / n1 + 1 / n2)
    if var <= 0:
        return None
    return (w1 / n1 - w2 / n2) / math.sqrt(var)
