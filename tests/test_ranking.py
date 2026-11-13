import pandas as pd
from conftest import df_aleatorio, df_de_ohlc

from binarias import backtest as bt
from binarias import ranking as rk
from binarias.estrategias import Estrategia, _sinais


def _df_previsivel(n=1000, acerto=0.7, seed=0):
    """Velas em que 'seguir a cor' acerta ~`acerto` das vezes."""
    import numpy as np

    rng = np.random.default_rng(seed)
    linhas, preco, cor = [], 100.0, 1
    for _ in range(n):
        cor = cor if rng.random() < acerto else -cor
        o, c = preco, preco + 0.1 * cor
        linhas.append((o, max(o, c) + 0.01, min(o, c) - 0.01, c))
        preco = c
    return df_de_ohlc(linhas)


def _est(nome, funcao):
    funcao.__name__ = nome
    return Estrategia(nome, nome[:4].upper(), funcao)


def seguir(df):
    c = df["close"] - df["open"]
    return _sinais(c > 0, c < 0)


def contra(df):
    c = df["close"] - df["open"]
    return _sinais(c < 0, c > 0)


def test_vantagem_comprovada_eh_escolhida():
    df = _df_previsivel(1200, acerto=0.70)
    r = rk.calcular_ranking(
        df,
        bt.ConfigBacktest(payout=0.85),
        janela=500,
        min_ops=100,
        estrategias=[_est("contra", contra), _est("seguir", seguir)],
    )
    assert r["melhor"] == "seguir"
    top = r["linhas"][0]
    assert top["id"] == "seguir" and top["janela"]["vantagem"]
    assert top["janela"]["ic_inf"] > r["break_even"]
    assert not r["linhas"][1]["janela"]["vantagem"]


def test_sem_vantagem_em_dado_aleatorio():
    from binarias.estrategias import ESTRATEGIAS

    r = rk.calcular_ranking(
        df_aleatorio(2000, seed=11), bt.ConfigBacktest(payout=0.85), janela=500, min_ops=100, estrategias=ESTRATEGIAS
    )
    assert r["melhor"] is None, "em passeio aleatório nada deveria ter vantagem com payout 85%"
    assert len(r["linhas"]) == len(ESTRATEGIAS)


def test_minimo_de_operacoes():
    df = _df_previsivel(300, acerto=0.9)  # ~300 ops no total
    r = rk.calcular_ranking(df, bt.ConfigBacktest(), janela=80, min_ops=100, estrategias=[_est("seguir", seguir)])
    assert r["linhas"][0]["janela"]["decididas"] < 100
    assert r["melhor"] is None


def test_elegiveis_restringem_melhor():
    df = _df_previsivel(1200, acerto=0.7)
    r = rk.calcular_ranking(df, bt.ConfigBacktest(), estrategias=[_est("seguir", seguir)], elegiveis=set())
    assert r["melhor"] is None


def test_perdendo_forca():
    antes = _df_previsivel(1500, acerto=0.75, seed=1)
    depois = _df_previsivel(500, acerto=0.5, seed=2)
    depois["epoch"] += antes["epoch"].iat[-1] + 60 - depois["epoch"].iat[0]
    df = pd.concat([antes, depois], ignore_index=True)
    r = rk.calcular_ranking(df, bt.ConfigBacktest(), janela=500, estrategias=[_est("seguir", seguir)])
    assert r["linhas"][0]["forca"]["estado"] == "perdendo força"


def test_estrategia_com_erro_nao_derruba_ranking():
    def quebrada(df):
        raise RuntimeError("bug")

    r = rk.calcular_ranking(
        df_aleatorio(300), bt.ConfigBacktest(), estrategias=[_est("quebrada", quebrada), _est("seguir", seguir)]
    )
    assert any(l["erro"] for l in r["linhas"]) and r["linhas"][-1]["id"] == "quebrada"
    assert not rk.tabela(r).empty


def test_janela_so_conta_operacoes_recentes():
    df = _df_previsivel(1000)
    r = rk.calcular_ranking(df, bt.ConfigBacktest(), janela=200, estrategias=[_est("seguir", seguir)])
    l = r["linhas"][0]
    assert l["janela"]["operacoes"] <= 200 < l["historico"]["operacoes"]
