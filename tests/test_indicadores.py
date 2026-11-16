"""Indicadores: valores de referência conhecidos e ausência de lookahead (truncar o futuro e comparar)."""

import numpy as np
import pandas as pd
import pytest
from conftest import df_aleatorio, df_de_ohlc

from binarias import indicadores as I


def _ema_manual(valores, periodo):
    """EMA pela definição de livro: e0 = x0; e_t = a·x_t + (1 − a)·e_{t−1}, a = 2/(N+1)."""
    a = 2 / (periodo + 1)
    saida, e = [], None
    for x in valores:
        e = x if e is None else a * x + (1 - a) * e
        saida.append(e)
    return np.array(saida)


# --------------------------------------------------------------------------- MACD
def test_macd_igual_a_definicao_de_livro():
    rng = np.random.default_rng(5)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    linha, sinal, hist = I.macd(close, 12, 26, 9)
    ref_linha = _ema_manual(close, 12) - _ema_manual(close, 26)
    assert np.allclose(linha.iloc[25:], ref_linha[25:])
    assert linha.iloc[:25].isna().all(), "aquecimento: as 25 primeiras ficam vazias"
    ref_sinal = _ema_manual(ref_linha[25:], 9)
    assert np.allclose(sinal.iloc[33:], ref_sinal[8:])
    assert np.allclose(hist.dropna(), (linha - sinal).dropna())


def test_macd_valores_conhecidos():
    """Preço constante -> MACD 0. Rampa linear de inclinação b -> linha converge para b·(26 − 12)/2 = 7b
    (atraso da EMA de N períodos numa rampa = b·(N − 1)/2), sinal também, histograma 0."""
    linha, sinal, hist = I.macd(pd.Series([50.0] * 100))
    assert np.allclose(linha.dropna(), 0) and np.allclose(hist.dropna(), 0)
    rampa = pd.Series(100 + 0.5 * np.arange(600, dtype=float))
    linha, sinal, hist = I.macd(rampa, 12, 26, 9)
    assert linha.iat[-1] == pytest.approx(3.5, abs=1e-6)
    assert sinal.iat[-1] == pytest.approx(3.5, abs=1e-6)
    assert hist.iat[-1] == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------- Estocástico, Williams %R, CCI
def _df_tres():
    # (open, high, low, close)
    return df_de_ohlc([(9, 10, 8, 9), (9, 12, 9, 11), (11, 11, 7, 10), (10, 13, 9, 13)])


def test_estocastico_valores_conhecidos():
    df = _df_tres()
    k, d = I.estocastico(df, k=3, d=2, suavizacao=1)
    # vela 2: máx(10,12,11)=12, mín(8,9,7)=7 -> 100·(10−7)/5 = 60
    # vela 3: máx(12,11,13)=13, mín(9,7,9)=7 -> 100·(13−7)/6 = 100
    assert k.iloc[:2].isna().all()
    assert k.iat[2] == pytest.approx(60.0) and k.iat[3] == pytest.approx(100.0)
    assert d.iat[3] == pytest.approx(80.0)
    lento, _ = I.estocastico(df, k=3, d=2, suavizacao=2)
    assert lento.iat[3] == pytest.approx(80.0)


def test_estocastico_faixa_parada_vale_50():
    df = df_de_ohlc([(5, 5, 5, 5)] * 5)
    k, _ = I.estocastico(df, k=3, d=1, suavizacao=1)
    assert (k.dropna() == 50).all()


def test_williams_r_valores_conhecidos():
    w = I.williams_r(_df_tres(), 3)
    assert w.iat[2] == pytest.approx(-40.0)  # −100·(12−10)/5
    assert w.iat[3] == pytest.approx(0.0)
    k, _ = I.estocastico(_df_tres(), k=3, d=1, suavizacao=1)
    assert np.allclose(w.dropna(), (k - 100).dropna()), "%R = %K rápido − 100"


def test_cci_valor_conhecido():
    df = _df_tres()
    v = I.cci(df, 3)
    tp = np.array([(10 + 8 + 9) / 3, (12 + 9 + 11) / 3, (11 + 7 + 10) / 3])
    desvio = np.abs(tp - tp.mean()).mean()
    assert v.iat[2] == pytest.approx((tp[-1] - tp.mean()) / (0.015 * desvio))
    assert v.iloc[:2].isna().all()


# --------------------------------------------------------------------------- Keltner, Donchian, VWAP, SuperTrend
def test_keltner_e_donchian():
    df = df_aleatorio(300, seed=4)
    sup, centro, inf = I.keltner(df, 20, 2.0, 10)
    assert np.allclose((sup - centro).dropna(), (2.0 * I.atr(df, 10))[sup.notna()])
    assert (sup.dropna() >= inf.dropna()).all()
    alta, meio, baixa = I.donchian(df, 10)
    assert alta.iat[50] == df["high"].iloc[41:51].max() and baixa.iat[50] == df["low"].iloc[41:51].min()
    alta_ant, _, _ = I.donchian(df, 10, incluir_atual=False)
    assert alta_ant.iat[50] == df["high"].iloc[40:50].max()
    assert meio.iat[50] == pytest.approx((alta.iat[50] + baixa.iat[50]) / 2)


def test_vwap_so_com_volume():
    df = df_aleatorio(100, seed=1)
    assert I.vwap(df) is None, "a Deriv não fornece volume: sem volume, sem VWAP"
    assert I.vwap(df.assign(volume=0)) is None
    com = df.assign(volume=np.arange(1, 101, dtype=float))
    v = I.vwap(com, 5)
    tp = (com["high"] + com["low"] + com["close"]) / 3
    esperado = (tp.iloc[95:100] * com["volume"].iloc[95:100]).sum() / com["volume"].iloc[95:100].sum()
    assert v.iat[-1] == pytest.approx(esperado)


def test_supertrend_segue_a_tendencia():
    subida = [(100 + i, 100.6 + i, 99.9 + i, 100.5 + i) for i in range(60)]
    queda = [(160 - i, 160.1 - i, 159.4 - i, 159.5 - i) for i in range(60)]
    df = df_de_ohlc(subida + queda)
    linha, direcao = I.supertrend(df, 10, 3.0)
    assert direcao.iloc[:10].isna().all()
    assert (direcao.iloc[20:60] == 1).all() and (linha.iloc[20:60] < df["low"].iloc[20:60]).all()
    assert (direcao.iloc[-20:] == -1).all() and (linha.iloc[-20:] > df["high"].iloc[-20:]).all()


# --------------------------------------------------------------------------- sem lookahead (todos)
def _series(resultado):
    if resultado is None:
        return []
    return list(resultado) if isinstance(resultado, tuple) else [resultado]


INDICADORES = {
    "ema": lambda df: I.ema(df["close"], 20),
    "macd": lambda df: I.macd(df["close"], 12, 26, 9),
    "estocastico": lambda df: I.estocastico(df, 14, 3, 3),
    "williams_r": lambda df: I.williams_r(df, 14),
    "cci": lambda df: I.cci(df, 20),
    "keltner": lambda df: I.keltner(df, 20, 2.0, 10),
    "donchian": lambda df: I.donchian(df, 20),
    "donchian_anteriores": lambda df: I.donchian(df, 20, incluir_atual=False),
    "vwap": lambda df: I.vwap(df.assign(volume=1.0 + np.arange(len(df)) % 7), 30),
    "supertrend": lambda df: I.supertrend(df, 10, 3.0),
    "rsi": lambda df: I.rsi(df["close"], 14),
    "atr": lambda df: I.atr(df, 14),
    "adx": lambda df: I.adx(df, 14),
    "bandas": lambda df: I.bandas(df["close"], 20, 2.0),
}


@pytest.mark.parametrize("nome", list(INDICADORES))
def test_indicador_sem_lookahead(nome):
    """O valor na vela i não pode mudar quando as velas depois de i são removidas."""
    f = INDICADORES[nome]
    df = df_aleatorio(800, seed=21)
    cheio = _series(f(df))
    assert cheio, nome
    for k in (40, 123, 400, 799):
        for a, b in zip(_series(f(df.iloc[:k])), cheio, strict=True):
            assert np.allclose(a.to_numpy(float), b.iloc[:k].to_numpy(float), equal_nan=True), f"{nome} (k={k})"
