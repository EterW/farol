import numpy as np
from conftest import df_aleatorio
from test_ranking import _df_previsivel, _est, seguir

from binarias import backtest as bt
from binarias import validacao as val
from binarias.estrategias import POR_ID


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


def test_relatorio_reporta_testes_multiplos():
    dfs = {"A": df_aleatorio(1500, seed=1), "B": df_aleatorio(1500, seed=2)}
    ests = [POR_ID["seguir_cor"], POR_ID["reversao_sequencia"], POR_ID["macd_cruzamento"]]
    wf = val.walk_forward_todos(dfs, bt.ConfigBacktest(), 0.7, 100, estrategias=ests)
    resumo, texto = val.relatorio(wf, bt.ConfigBacktest(), 100)
    assert resumo.attrs["hipoteses"] == 6
    assert resumo.attrs["combinacoes"] == 2 * sum(len(e.combinacoes()) for e in ests)
    assert "6 hipóteses fora da amostra" in texto
    for nome in ("Bonferroni", "Holm", "Benjamini-Hochberg"):
        assert nome in texto
    assert {"pares_significativos_holm", "menor_p_holm"} <= set(resumo.columns)


def _linha_wf(ativo, k, fraca):
    return {
        "ativo": ativo,
        "estrategia": f"E{k}",
        "id": f"e{k}",
        "params_escolhidos": "",
        "combinacoes_testadas": 1,
        "treino_ops": 300,
        "treino_decididas": 300,
        "treino_wins": 150,
        "treino_acerto_%": 50.0,
        "treino_ic95_inf_%": 44.0,
        "treino_ic95_sup_%": 56.0,
        "treino_lucro": 0.0,
        "treino_vantagem": False,
        "teste_ops": 280,
        "teste_decididas": 280,
        "teste_wins": 176 if fraca else 140,
        "teste_acerto_%": 62.9 if fraca else 50.0,
        "teste_ic95_inf_%": 57.1 if fraca else 44.0,
        "teste_ic95_sup_%": 68.3,
        "teste_lucro": 10.0,
        "teste_vantagem": fraca,
        "erro": "",
    }


def test_passa_exige_holm():
    """Vantagem no teste por pouco em cada par, mas não significativa após Holm (20 hipóteses) -> não passa."""
    import pandas as pd

    wf = pd.DataFrame([_linha_wf(a, k, k == 0) for a in ("A", "B") for k in range(10)])
    resumo, texto = val.relatorio(wf, bt.ConfigBacktest(), 100)
    e0 = resumo[resumo["estrategia"] == "E0"].iloc[0]
    assert e0["pares_com_vantagem_no_teste"] == 2 and e0["pares_significativos_holm"] == 0
    assert not e0["PASSA_EM_TODOS"] and "NENHUMA ESTRATÉGIA PASSOU" in texto
