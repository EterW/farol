import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

INICIO = 1_699_999_800  # múltiplo de 60 e de 300 -> posição 0 do quadrante MHI


def df_de_ohlc(linhas, gran=60, inicio=INICIO):
    """linhas: lista de (open, high, low, close)."""
    df = pd.DataFrame(linhas, columns=["open", "high", "low", "close"], dtype=float)
    df.insert(0, "epoch", inicio + gran * np.arange(len(df), dtype="int64"))
    return df


def df_de_cores(cores, gran=60, inicio=INICIO):
    """1 = verde, -1 = vermelha, 0 = doji. Cada vela abre no fechamento da anterior."""
    linhas, preco = [], 100.0
    for c in cores:
        o = preco
        f = o + 0.1 * c
        linhas.append((o, max(o, f) + 0.05, min(o, f) - 0.05, f))
        preco = f
    return df_de_ohlc(linhas, gran, inicio)


def df_aleatorio(n=1500, seed=0, gran=60, inicio=INICIO, tendencia=0.0):
    rng = np.random.default_rng(seed)
    fech = 100 + np.cumsum(rng.normal(tendencia, 0.1, n))
    abert = np.r_[100.0, fech[:-1]] + rng.normal(0, 0.02, n)
    alta = np.maximum(abert, fech) + rng.exponential(0.05, n)
    baixa = np.minimum(abert, fech) - rng.exponential(0.05, n)
    return df_de_ohlc(list(zip(abert, alta, baixa, fech)), gran, inicio)


@pytest.fixture
def aleatorio():
    return df_aleatorio()
