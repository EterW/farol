"""'Minha banca': contas, limites do dia e simulador 'e se' (sem martingale)."""

import pytest
from fastapi.testclient import TestClient

from binarias import risco as R


def test_valor_de_entrada_e_avisos():
    v = R.valor_entrada(1000, 2)
    assert v["valor"] == 20.0 and v["avisos"] == []
    assert R.valor_entrada(1000, 1.5)["valor"] == 15.0
    assert R.valor_entrada(1000, 3)["avisos"][0]["nivel"] == "medio"
    alto = R.valor_entrada(1000, 6)
    assert alto["valor"] == 60.0 and alto["avisos"][0]["nivel"] == "alto"
    with pytest.raises(ValueError):
        R.valor_entrada(-1, 2)
    with pytest.raises(ValueError):
        R.valor_entrada(1000, "abc")


def test_resultado_de_cada_operacao():
    assert R.resultado_operacao("WIN", 10, 0.85) == 8.5
    assert R.resultado_operacao("loss", 10, 0.85) == -10
    assert R.resultado_operacao("EMPATE", 10, 0.85) == 0
    with pytest.raises(ValueError):
        R.resultado_operacao("GALE", 10, 0.85)


def _op(r, valor=20, payout=0.85):
    return {"resultado": r, "valor": valor, "payout": payout}


def test_dia_sem_bloqueio_e_distancia_ao_limite():
    d = R.estado_dia(1000, [_op("WIN"), _op("LOSS")], perda_max_pct=5, parar_apos=3)
    assert d["resultado"] == -3.0 and d["banca_atual"] == 997.0
    assert d["limite_perda"] == 50.0 and d["distancia_limite"] == 47.0
    assert not d["bloqueado"] and d["losses_seguidos"] == 1


def test_bloqueia_na_perda_maxima_do_dia():
    d = R.estado_dia(1000, [_op("LOSS", 25), _op("WIN", 10), _op("LOSS", 25)], perda_max_pct=5, parar_apos=0)
    assert d["resultado"] == -41.5 and not d["bloqueado"]
    d = R.estado_dia(1000, [_op("LOSS", 25), _op("LOSS", 25)], perda_max_pct=5, parar_apos=0)
    assert d["resultado"] == -50 and d["bloqueado"] and d["distancia_limite"] == 0
    assert "Limite do dia atingido: pare por hoje" in d["motivo"]


def test_bloqueia_apos_n_losses_seguidos_e_empate_nao_zera():
    ops = [_op("LOSS", 1), _op("LOSS", 1), _op("EMPATE", 1), _op("LOSS", 1)]
    d = R.estado_dia(1000, ops, perda_max_pct=50, parar_apos=3)
    assert d["losses_seguidos"] == 3 and d["bloqueado"] and "3 losses seguidos" in d["motivo"]
    ops = [_op("LOSS", 1), _op("LOSS", 1), _op("WIN", 1), _op("LOSS", 1)]
    assert not R.estado_dia(1000, ops, 50, 3)["bloqueado"], "WIN zera a sequência"


def test_meta_do_dia():
    d = R.estado_dia(1000, [_op("WIN", 20)] * 3, meta_pct=5)
    assert d["meta"] == 50.0 and d["meta_atingida"] and not d["bloqueado"]
    assert R.estado_dia(1000, [], meta_pct=None)["meta"] is None


def test_simulador_valor_esperado_exato():
    s = R.simular(0.60, 0.85, 2, 100, 2000)
    # EV por operação = 0,6×0,85 − 0,4 = 0,11 entrada; 100 operações × 2% × 0,11 = 22% da banca
    assert s["esperado_pct_banca"] == pytest.approx(22.0)
    assert not s["abaixo_break_even"] and s["avisos"] == []
    assert 0 <= s["prob_ruina"] <= 1 and s["p5_final_pct"] <= s["mediana_final_pct"] <= s["p95_final_pct"]


def test_abaixo_do_break_even_da_prejuizo_em_qualquer_gestao():
    for pct in (0.5, 1, 2, 5, 10):
        s = R.simular(0.50, 0.85, pct, 100, 3000)
        assert s["esperado_pct_banca"] < 0, pct
        assert s["abaixo_break_even"] and R.AVISO_BREAK_EVEN in s["avisos"]
        assert s["mediana_final_pct"] < 0 and s["prob_prejuizo"] > 0.5


def test_ruina_cresce_com_o_tamanho_da_entrada():
    pequena = R.simular(0.52, 0.85, 1, 200, 4000)["prob_ruina"]
    grande = R.simular(0.52, 0.85, 10, 200, 4000)["prob_ruina"]
    assert grande > pequena and grande > 0.5


def test_quebra_para_de_operar():
    s = R.simular(0.0, 0.85, 30, 50, 200)
    assert s["prob_ruina"] == 1.0 and s["mediana_final_pct"] >= -100


def test_api_risco():
    from binarias.servidor import app

    with TestClient(app) as c:
        r = c.post(
            "/api/risco/dia",
            json={"banca": 1000, "pct": 2, "operacoes": [_op("LOSS")] * 3, "perda_max_pct": 5, "parar_apos": 3},
        )
        assert r.status_code == 200 and r.json()["dia"]["bloqueado"] and r.json()["entrada"]["valor"] == 20
        r = c.post("/api/risco/simular", json={"acerto": 0.5, "payout": 0.85, "pct": 2})
        assert r.status_code == 200 and r.json()["abaixo_break_even"]
        assert c.post("/api/risco/simular", json={"acerto": 2}).status_code == 400
        assert c.post("/api/risco/dia", content=b"xx").status_code == 400
