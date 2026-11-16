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


# --------------------------------------------------------------------------- testes múltiplos
ALFA_UNILATERAL = (1 - CONFIANCA) / 2  # 2,5%: o mesmo nível do limite inferior do IC de Wilson 95%
METODOS_CORRECAO = {"bonferroni": "Bonferroni", "holm": "Holm", "bh": "Benjamini-Hochberg (FDR)"}


def p_valor_acima(acertos: int, n: int, p0: float) -> float:
    """p-valor exato (binomial, unilateral) de H0: acerto <= p0 contra H1: acerto > p0.
    = P(X >= acertos) com X ~ Binomial(n, p0). n = 0 -> 1 (nenhuma evidência)."""
    if n <= 0 or acertos <= 0:
        return 1.0
    if acertos > n:
        return 0.0
    if p0 <= 0:
        return 0.0
    if p0 >= 1:
        return 1.0
    lp, lq = math.log(p0), math.log1p(-p0)
    base = math.lgamma(n + 1)
    termos = [base - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq for k in range(acertos, n + 1)]
    m = max(termos)
    return min(1.0, math.exp(m) * sum(math.exp(t - m) for t in termos))


def ajustar_p(pvalores: list[float], metodo: str = "holm") -> list[float]:
    """p-valores ajustados para testes múltiplos (mesma ordem da entrada).
    bonferroni: p·m.  holm: passo a passo (controla o erro de família, mais poderoso que Bonferroni).
    bh: Benjamini-Hochberg (controla a taxa de falsas descobertas, FDR; mais permissivo)."""
    m = len(pvalores)
    if m == 0:
        return []
    if metodo == "bonferroni":
        return [min(1.0, p * m) for p in pvalores]
    ordem = sorted(range(m), key=lambda i: pvalores[i])
    ajust = [1.0] * m
    if metodo == "holm":
        acumulado = 0.0
        for posicao, i in enumerate(ordem):
            acumulado = max(acumulado, min(1.0, (m - posicao) * pvalores[i]))
            ajust[i] = acumulado
        return ajust
    if metodo == "bh":
        acumulado = 1.0
        for posicao in range(m - 1, -1, -1):
            i = ordem[posicao]
            acumulado = min(acumulado, pvalores[i] * m / (posicao + 1))
            ajust[i] = min(1.0, acumulado)
        return ajust
    raise ValueError(f"método de correção desconhecido: {metodo} (use {', '.join(METODOS_CORRECAO)})")
