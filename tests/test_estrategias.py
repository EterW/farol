import numpy as np
import pandas as pd
import pytest
from conftest import df_aleatorio, df_de_cores, df_de_ohlc

from binarias import estrategias as E

ESTS = E.ESTRATEGIAS
IDS = [e.id for e in ESTS]


def _igual(a: pd.Series, b: pd.Series) -> bool:
    return a.fillna("-").tolist() == b.fillna("-").tolist()


@pytest.mark.parametrize("est", ESTS, ids=IDS)
def test_formato_sinais_e_condicoes(est, aleatorio):
    s = est.gerar_sinais(aleatorio)
    assert isinstance(s, pd.Series) and s.index.equals(aleatorio.index)
    assert set(s.dropna().unique()) <= {"CALL", "PUT"}
    conds = est.gerar_condicoes(aleatorio)
    assert conds and all(c.texto_call and c.texto_put for c in conds)
    assert all(c.call.index.equals(aleatorio.index) and c.put.index.equals(aleatorio.index) for c in conds)


@pytest.mark.parametrize("est", ESTS, ids=IDS)
def test_sinal_eh_exatamente_todas_as_condicoes(est):
    """O progresso conta as condições; elas precisam ser EXATAMENTE as que geram o sinal."""
    df = df_aleatorio(2000, seed=13)
    for params in est.combinacoes()[:4]:
        s = est.gerar_sinais(df, **params)
        conds = est.gerar_condicoes(df, **params)
        call = pd.concat([c.call.fillna(False).astype(bool) for c in conds], axis=1).all(axis=1)
        put = pd.concat([c.put.fillna(False).astype(bool) for c in conds], axis=1).all(axis=1)
        assert ((s == "CALL") == (call & ~put)).all() and ((s == "PUT") == (put & ~call)).all()


def test_estrategia_sem_condicoes_usa_o_sinal():
    def so_verde(df):
        return E._sinais(df["close"] > df["open"], df["close"] < df["open"])

    est = E.Estrategia("Só verde", "SV", so_verde)
    df = df_aleatorio(100, seed=2)
    (c,) = est.gerar_condicoes(df)
    assert (c.call == (est.gerar_sinais(df) == "CALL")).all()


@pytest.mark.parametrize("est", ESTS, ids=IDS)
def test_estrategia_gera_algum_sinal(est):
    df = df_aleatorio(3000, seed=3)
    assert est.gerar_sinais(df).notna().any(), "estratégia nunca dispara em 3000 velas aleatórias"


@pytest.mark.parametrize("est", ESTS, ids=IDS)
def test_sem_lookahead(est):
    """O sinal da vela i não pode mudar quando as velas posteriores a i são removidas."""
    df = df_aleatorio(1200, seed=7)
    for params in est.combinacoes()[:4]:
        cheio_s = est.gerar_sinais(df, **params)
        cheio_c = est.gerar_condicoes(df, **params)
        for k in (60, 201, 555, 999):
            parte = df.iloc[:k]
            assert _igual(est.gerar_sinais(parte, **params), cheio_s.iloc[:k]), f"sinal olha o futuro (k={k}, {params})"
            for a, b in zip(est.gerar_condicoes(parte, **params), cheio_c, strict=True):
                assert a.call.fillna(False).tolist() == b.call.iloc[:k].fillna(False).tolist(), "condição olha o futuro"
                assert a.put.fillna(False).tolist() == b.put.iloc[:k].fillna(False).tolist(), "condição olha o futuro"


def _lista(s):
    return [v if v in ("CALL", "PUT") else None for v in s]


def test_detector_de_lookahead_funciona():
    """Uma estratégia 'trapaceira' (usa a vela seguinte) precisa ser pega pelo teste acima."""

    def trapaca(df):
        prox = df["close"].shift(-1)
        return E._sinais(prox > df["close"], prox < df["close"])

    df = df_aleatorio(300, seed=1)
    assert not _igual(trapaca(df.iloc[:200]), trapaca(df).iloc[:200])


def test_sinais_conflitantes_sao_descartados():
    idx = pd.RangeIndex(3)
    s = E._sinais(pd.Series([True, True, False], index=idx), pd.Series([True, False, True], index=idx))
    assert _lista(s) == [None, "CALL", "PUT"]


def test_seguir_cor():
    df = df_de_cores([1, -1, 0, 1])
    assert _lista(E.seguir_cor(df)) == ["CALL", "PUT", None, "CALL"]


def test_reversao_sequencia():
    df = df_de_cores([1, 1, 1, -1, -1, -1, 1, 1])
    s = E.reversao_sequencia(df, n=3)
    assert s[2] == "PUT" and s[5] == "CALL"
    assert s.drop([2, 5]).isna().all()
    conds = E.reversao_sequencia_condicoes(df, n=3)
    assert [bool(c.put.iat[1]) for c in conds] == [True, True, False]  # 2 de 3 verdes: falta uma
    assert [c.texto_put for c in conds] == ["Vela atual verde", "Vela anterior verde", "Vela de 2 atrás verde"]


def test_cruzamento_nao_dispara_quando_medias_ficam_iguais():
    subida = list(np.linspace(100, 104, 40))
    plano = [subida[-1]] * 30  # depois de 20 velas planas as médias ficam IGUAIS
    queda = list(np.linspace(subida[-1] - 0.1, subida[-1] - 2, 10))
    fech = subida + plano + queda
    df = df_de_ohlc([(c, c + 0.01, c - 0.01, c) for c in fech])
    s = E.cruzamento_medias(df, 5, 20)
    assert s.iloc[40:70].isna().all(), "igualdade das médias não é cruzamento"
    assert (s.iloc[70:] == "PUT").sum() == 1, "o cruzamento real para baixo deve gerar 1 PUT"


def test_mhi_minoria_nas_3_ultimas_do_quadrante():
    # posições 0..4 do quadrante; as 3 últimas (2,3,4) = verde, verde, vermelha -> maioria verde -> PUT
    df = df_de_cores([1, 1, 1, 1, -1, 1, -1, -1, -1, 1])
    s = E.mhi(df)
    assert s[4] == "PUT"
    assert s[9] == "CALL"  # 2ª janela: vermelha, vermelha, verde -> minoria verde
    assert s.drop([4, 9]).isna().all()


def test_mhi_ignora_doji_e_buraco():
    df = df_de_cores([1, 1, 1, 0, -1])
    assert E.mhi(df).isna().all()
    df = df_de_cores([1, 1, 1, 1, -1, 1, 1, 1, 1, -1])
    df.loc[8:, "epoch"] += 300  # buraco de 5 min entre as velas 7 e 8 (posições 2 e 3)
    s = E.mhi(df)
    assert s[4] == "PUT"
    assert pd.isna(s.iloc[-1]), "não pode usar velas separadas por buraco de mercado"
    df_sem_buraco = df_de_cores([1, 1, 1, 1, -1, 1, 1, 1, 1, -1])
    assert E.mhi(df_sem_buraco).iloc[-1] == "PUT"


def test_rompimento_e_rejeicao():
    linhas = (
        [(100, 101, 99, 100)] * 25
        + [(100, 103, 100, 102.5)]
        + [(101, 103.5, 100.5, 102)]  # passa da máxima anterior (103) e fecha dentro
        + [(100, 100.5, 98.5, 99.5)]
    )  # passa da mínima anterior (99) e fecha dentro
    df = df_de_ohlc(linhas)
    assert E.rompimento_sr(df, n=20)[25] == "CALL"
    rej = E.rejeicao_sr(df, n=20)
    assert rej[26] == "PUT" and rej[27] == "CALL"


def test_combinacoes_incluem_padrao():
    for est in ESTS:
        combos = est.combinacoes()
        assert dict(est.parametros) in combos
        assert len(combos) == len({tuple(sorted(c.items())) for c in combos})


def test_registro_consistente():
    assert len(set(IDS)) == len(IDS)
    assert len({e.sigla for e in ESTS}) == len(ESTS)
    for e in ESTS:
        assert e.descricao and "\n" not in e.descricao
