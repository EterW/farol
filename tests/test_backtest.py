import pandas as pd
import pytest

from binarias import backtest as bt
from conftest import df_de_ohlc


def _df(pares):
    """pares: lista de (open, close)."""
    return df_de_ohlc([(o, max(o, c) + 1, min(o, c) - 1, c) for o, c in pares])


def _sinais(df, mapa):
    s = pd.Series(None, index=df.index, dtype=object)
    for i, d in mapa.items():
        s[i] = d
    return s


@pytest.mark.parametrize("direcao,entrada,saida,empate,esperado", [
    ("CALL", 100, 101, "devolve", "WIN"), ("CALL", 100, 99, "devolve", "LOSS"),
    ("PUT", 100, 99, "devolve", "WIN"), ("PUT", 100, 101, "devolve", "LOSS"),
    ("CALL", 100, 100, "devolve", "EMPATE"), ("PUT", 100, 100, "perde", "LOSS"),
])
def test_resolver(direcao, entrada, saida, empate, esperado):
    assert bt.resolver(direcao, entrada, saida, empate) == esperado


def test_entrada_na_abertura_seguinte_e_payout():
    df = _df([(10, 11), (100, 101), (101, 100)])
    r = bt.executar(df, _sinais(df, {0: "CALL"}), bt.ConfigBacktest(payout=0.85, valor_entrada=10))
    op = r.operacoes.iloc[0]
    assert (op.idx_sinal, op.idx_fim, op.preco_entrada, op.preco_saida) == (0, 1, 100, 101)
    assert op.resultado == "WIN" and op.lucro == 8.5
    assert r.resumo["banca_final"] == 1008.5


def test_expiracao_2_velas():
    df = _df([(10, 11), (100, 99), (99, 102), (0, 0)])
    r = bt.executar(df, _sinais(df, {0: "CALL"}), bt.ConfigBacktest(expiracao=2))
    op = r.operacoes.iloc[0]
    assert (op.preco_entrada, op.preco_saida, op.resultado, op.idx_fim) == (100, 102, "WIN", 2)


def test_empate_devolve_ou_perde():
    df = _df([(10, 11), (100, 100)])
    s = _sinais(df, {0: "PUT"})
    assert bt.executar(df, s, bt.ConfigBacktest(empate="devolve")).operacoes.iloc[0].lucro == 0
    op = bt.executar(df, s, bt.ConfigBacktest(empate="perde")).operacoes.iloc[0]
    assert op.resultado == "LOSS" and op.lucro == -10


def test_sem_sobreposicao_mas_sinal_no_fechamento_da_expiracao_vale():
    df = _df([(i, i + 1) for i in range(10)])
    sinais = pd.Series("CALL", index=df.index, dtype=object)
    r = bt.executar(df, sinais, bt.ConfigBacktest(expiracao=2))
    assert r.operacoes["idx_sinal"].tolist() == [0, 2, 4, 6]  # 8 não cabe (expira na vela 10)


def test_operacao_incompleta_descartada():
    df = _df([(1, 2), (2, 3), (3, 4)])
    r = bt.executar(df, _sinais(df, {2: "CALL"}), bt.ConfigBacktest())
    assert r.operacoes.empty and r.resumo["operacoes"] == 0


def test_gale():
    df = _df([(0, 0), (100, 99), (99, 100)])  # perde na 1ª, ganha no gale
    r = bt.executar(df, _sinais(df, {0: "CALL"}), bt.ConfigBacktest(gales=1, fator_gale=2, valor_entrada=10, payout=0.85))
    op = r.operacoes.iloc[0]
    assert op.gale == 1 and op.resultado == "WIN" and op.lucro == pytest.approx(-10 + 20 * 0.85)
    assert r.resumo["wins_gale_1"] == 1 and "acerto_break_even_%" not in r.resumo


def test_gale_sem_dados_descarta():
    df = _df([(0, 0), (100, 99)])
    r = bt.executar(df, _sinais(df, {0: "CALL"}), bt.ConfigBacktest(gales=1))
    assert r.operacoes.empty


def test_resumo_estatistico():
    pares = [(0, 0)] + [(100, 101), (101, 100)] * 50  # alterna win/loss
    df = _df(pares)
    sinais = pd.Series("CALL", index=df.index, dtype=object)
    r = bt.executar(df, sinais, bt.ConfigBacktest(payout=0.85))
    res = r.resumo
    assert res["wins"] + res["losses"] == res["operacoes"]
    assert res["ic95_inf_%"] < res["acerto_%"] < res["ic95_sup_%"]
    assert res["acerto_break_even_%"] == pytest.approx(54.05, abs=0.01)


def test_config_invalida():
    with pytest.raises(ValueError):
        bt.ConfigBacktest(empate="talvez")
    with pytest.raises(ValueError):
        bt.ConfigBacktest(payout=85)
