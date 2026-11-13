import numpy as np
import pandas as pd

from binarias import backtest as bt, validacao as val
from binarias.estrategias import ESTRATEGIAS, POR_ID
from conftest import df_aleatorio
from test_ranking import _df_previsivel, _est, seguir


def test_walk_forward_nao_olha_o_teste():
    """Trocar completamente os 30% finais não pode mudar os parâmetros escolhidos nem o resultado do treino."""
    df = df_aleatorio(2000, seed=8)
    corte = int(len(df) * 0.7)
    outro = df.copy()
    rng = np.random.default_rng(99)
    ruido = rng.normal(0, 0.5, len(df) - corte)
    for c in ("open", "high", "low", "close"):
        outro.loc[corte:, c] = outro.loc[corte:, c].to_numpy() + ruido
    for est in (POR_ID["reversao_sequencia"], POR_ID["rompimento_sr"], POR_ID["cruzamento_medias"]):
        a = val.walk_forward(df, est, bt.ConfigBacktest(), 0.7, 100)
        b = val.walk_forward(outro, est, bt.ConfigBacktest(), 0.7, 100)
        assert a["params"] == b["params"] and a["treino"] == b["treino"], est.id


def test_trechos_nao_se_sobrepoem():
    df = df_aleatorio(1000, seed=2)
    est = POR_ID["seguir_cor"]
    cfg = bt.ConfigBacktest()
    tr = val.avaliar_trecho(df, est, {}, cfg, 0, 700, 100)
    te = val.avaliar_trecho(df, est, {}, cfg, 700, 1000, 100)
    total = val.avaliar_trecho(df, est, {}, cfg, 0, 1000, 100)
    assert abs(tr["operacoes"] + te["operacoes"] - total["operacoes"]) <= 1


def test_escolhe_melhor_combinacao_no_treino():
    df = _df_previsivel(3000, acerto=0.7)
    wf = val.walk_forward(df, POR_ID["reversao_sequencia"], bt.ConfigBacktest(), 0.7, 100)
    assert wf["combinacoes"] == 4 and wf["params"]["n"] in (2, 3, 4, 5)
    assert wf["treino"]["decididas"] > 0 and wf["teste"]["decididas"] > 0


def test_relatorio_quando_nada_passa():
    dfs = {"A": df_aleatorio(1500, seed=1), "B": df_aleatorio(1500, seed=2)}
    ests = [POR_ID["seguir_cor"], POR_ID["engolfo"]]
    wf = val.walk_forward_todos(dfs, bt.ConfigBacktest(), 0.7, 100, estrategias=ests)
    resumo, texto = val.relatorio(wf, bt.ConfigBacktest(), 100)
    assert not resumo["PASSA_EM_TODOS"].any()
    assert "NENHUMA ESTRATÉGIA PASSOU NA VALIDAÇÃO" in texto
    comp = val.comparativo(dfs, bt.ConfigBacktest(), estrategias=ests)
    assert len(comp) == 4 and "total_acerto_%" in comp


def test_relatorio_quando_passa():
    dfs = {"A": _df_previsivel(2000, 0.72, seed=1), "B": _df_previsivel(2000, 0.72, seed=2)}
    wf = val.walk_forward_todos(dfs, bt.ConfigBacktest(), 0.7, 100, estrategias=[_est("seguir", seguir)])
    resumo, texto = val.relatorio(wf, bt.ConfigBacktest(), 100)
    assert resumo["PASSA_EM_TODOS"].all() and "PASSARAM EM TODOS OS PARES" in texto
