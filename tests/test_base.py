"""Testes de timeframes, CSV e estatística."""

import pandas as pd
import pytest
from conftest import INICIO, df_aleatorio

from binarias import dados
from binarias import estatistica as st
from binarias import timeframes as tf


def test_parse_e_nome_timeframe():
    assert tf.parse_timeframe("m20") == 1200 and tf.parse_timeframe("H4") == 14400
    assert tf.nome_timeframe(3600) == "H1" and tf.nome_timeframe(tf.parse_timeframe("M60")) == "H1"
    for ruim in ("", "X5", "M0", "M-1", "5M"):
        with pytest.raises(ValueError):
            tf.parse_timeframe(ruim)
    assert tf.granularidade_base(1200) == 600 and tf.granularidade_base(420) == 60


def test_agregar_m1_para_m5():
    base = df_aleatorio(23, gran=60, inicio=INICIO + 120)  # começa no meio de uma vela M5
    fechadas, formando = tf.agregar(base, 300, 60)
    # 1ª M5 incompleta (3 velas) descartada; última (23-3=20 -> 4 completas, 0 sobra)
    assert fechadas["epoch"].tolist() == [INICIO + 300 * k for k in range(1, 5)]
    assert formando.empty
    g = base[(base.epoch >= INICIO + 300) & (base.epoch < INICIO + 600)]
    v = fechadas.iloc[0]
    assert (v.open, v.high, v.low, v.close) == (g.open.iat[0], g.high.max(), g.low.min(), g.close.iat[-1])


def test_agregar_com_relogio_separa_vela_em_formacao():
    base = df_aleatorio(12, gran=60)
    agora = INICIO + 60 * 12 - 30  # no meio da 12ª vela M1 -> M5 da posição 10 em formação
    fechadas, formando = tf.agregar(base, 300, 60, agora)
    assert len(fechadas) == 2 and formando["epoch"].tolist() == [INICIO + 600]


def test_carregar_csv_limpa_duplicadas_e_desalinhadas(tmp_path):
    df = df_aleatorio(50, gran=300)
    sujo = pd.concat([df, df.iloc[[5]], df.iloc[[10]].assign(epoch=df.epoch[10] + 299)])
    caminho = tmp_path / "x.csv"
    sujo.to_csv(caminho, index=False)
    limpo = dados.carregar_csv(str(caminho))
    assert len(limpo) == 50 and (limpo.epoch % 300 == 0).all() and limpo.epoch.is_monotonic_increasing


def test_wilson_valores_conhecidos():
    inf, sup = st.wilson(50, 100)
    assert inf == pytest.approx(0.4038, abs=1e-4) and sup == pytest.approx(0.5962, abs=1e-4)
    assert st.wilson(0, 0) == (0.0, 1.0)
    inf, sup = st.wilson(0, 10)
    assert inf == pytest.approx(0.0, abs=1e-12) and 0 < sup < 0.35


def test_break_even_e_z():
    assert st.break_even(0.85) == pytest.approx(0.54054, abs=1e-5)
    assert st.break_even(1.0) == 0.5
    assert st.z_duas_proporcoes(40, 100, 60, 100) < -2.5
    assert st.z_duas_proporcoes(1, 0, 1, 1) is None
