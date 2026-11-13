import numpy as np
from conftest import df_aleatorio, df_de_ohlc

from binarias import indicadores as ind
from binarias import mercado


def _serie(fech, ruido=0.0, seed=0):
    rng = np.random.default_rng(seed)
    fech = np.asarray(fech, float) + rng.normal(0, ruido, len(fech))
    abert = np.r_[fech[0], fech[:-1]]
    return df_de_ohlc([(o, max(o, c) + 0.02, min(o, c) - 0.02, c) for o, c in zip(abert, fech)])


def test_tendencia_de_alta_forte():
    a = mercado.analisar(_serie(np.linspace(100, 130, 300), 0.05))
    assert a["ok"] and a["tendencia"] == "ALTA" and a["forca"] == "forte" and a["adx"] >= 25
    assert a["distancia_ma_atr"] > 0 and "ALTA" in a["resumo"]


def test_tendencia_de_baixa():
    a = mercado.analisar(_serie(np.linspace(130, 100, 300), 0.05))
    assert a["tendencia"] == "BAIXA"


def test_lateral():
    x = np.arange(400)
    a = mercado.analisar(_serie(100 + np.sin(x / 3), 0.05))
    assert a["tendencia"] == "LATERAL"


def test_vela_em_formacao_e_volatilidade():
    df = df_aleatorio(600, seed=4)
    formando = df_de_ohlc([(100, 101, 99, 99.5)])
    a = mercado.analisar(df, formando)
    assert a["vela_atual"] == {**a["vela_atual"], "direcao": "BAIXA", "fonte": "em formação"}
    assert 0 <= a["atr_percentil"] <= 100 and a["volatilidade"] in (
        "muito baixa",
        "baixa",
        "normal",
        "alta",
        "muito alta",
    )


def test_poucas_velas():
    a = mercado.analisar(df_aleatorio(30))
    assert not a["ok"] and "poucas velas" in a["motivo"]


def test_adx_intervalo_e_rsi():
    df = df_aleatorio(800, seed=2)
    v, mais, _menos = ind.adx(df)
    assert v.dropna().between(0, 100).all() and mais.dropna().ge(0).all()
    r = ind.rsi(df["close"], 14).dropna()
    assert r.between(0, 100).all()
    sobe = ind.rsi(df_de_ohlc([(i, i + 1, i, i + 1) for i in range(30)])["close"], 14)
    assert sobe.iloc[-1] == 100  # sem perdas -> 100 (antes virava NaN)
