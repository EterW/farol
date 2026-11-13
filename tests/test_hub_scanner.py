import asyncio
import time

import pytest

from binarias import backtest as bt, hub as hubmod, scanner
from conftest import df_aleatorio
from fake_deriv import FakeDeriv


def rodar(coro, timeout=30):
    return asyncio.run(asyncio.wait_for(coro, timeout))


async def _esperar(cond, timeout=8.0):
    t0 = time.time()
    while not cond():
        if time.time() - t0 > timeout:
            raise AssertionError("condição não atingida a tempo")
        await asyncio.sleep(0.05)


# --------------------------------------------------------------------------- hub
def test_uma_conexao_assinaturas_reaproveitadas_e_paginacao():
    async def cenario():
        async with FakeDeriv() as fake:
            h = hubmod.DerivHub(fake.url, intervalo=0)
            h.iniciar()
            try:
                a = await h.obter_serie("frxEURUSD", 60, 2000)
                b = await h.obter_serie("frxEURUSD", 60, 2000)   # mesma série
                c = await h.obter_serie("frxGBPUSD", 60, 500)
                assert a is b and a.refs == 2
                await asyncio.wait_for(a.pronta.wait(), 10)
                await asyncio.wait_for(c.pronta.wait(), 10)
                assert len(a.velas) >= 2000, "paginação (900 por resposta) deve completar 2000 velas"
                assert fake.conexoes == 1 and h.conexoes_abertas == 1
                assert fake.contar(ticks_history="frxEURUSD", subscribe=1) == 1
                assert fake.contar(ticks_history="frxGBPUSD", subscribe=1) == 1
                v0 = a.versao
                await _esperar(lambda: a.versao > v0 + 3)  # recebendo ohlc ao vivo
                assert a.casas == 5 and a.sub_id
            finally:
                await h.fechar()
    rodar(cenario())


def test_reconecta_e_reassina_apos_queda():
    async def cenario():
        async with FakeDeriv(derrubar_apos=1.0) as fake:
            h = hubmod.DerivHub(fake.url, intervalo=0)
            h.iniciar()
            try:
                s = await h.obter_serie("frxEURUSD", 60, 300)
                await asyncio.wait_for(s.pronta.wait(), 10)
                await _esperar(lambda: fake.conexoes == 2 and h.conectado.is_set() and s.sub_id
                               and s.sub_id.startswith("sub-2"))
                assert fake.contar(ticks_history="frxEURUSD", subscribe=1) == 2
                v = s.versao
                await _esperar(lambda: s.versao > v + 2)  # dados voltaram a chegar
                assert h.status["quedas"] >= 1
            finally:
                await h.fechar()
    rodar(cenario())


def test_rate_limit_com_backoff(monkeypatch):
    monkeypatch.setattr(hubmod, "backoff", lambda *a, **k: 0.05)
    async def cenario():
        async with FakeDeriv(rate_limit_primeiros=2) as fake:
            h = hubmod.DerivHub(fake.url, intervalo=0)
            h.iniciar()
            try:
                s = await h.obter_serie("frxEURUSD", 60, 100)
                await asyncio.wait_for(s.pronta.wait(), 10)
                assert s.erro is None and len(s.velas) >= 100
            finally:
                await h.fechar()
    rodar(cenario())


def test_mercado_fechado_e_liberacao(monkeypatch):
    monkeypatch.setattr(hubmod, "ESPERA_LIBERAR", 0.1)
    async def cenario():
        async with FakeDeriv(fechados={"frxFECHADO"}) as fake:
            h = hubmod.DerivHub(fake.url, intervalo=0)
            h.iniciar()
            try:
                f = await h.obter_serie("frxFECHADO", 60, 100)
                await asyncio.wait_for(f.pronta.wait(), 10)
                assert f.mercado_fechado and f.velas and f.sub_id is None
                lista = await h.ativos()
                assert h.bolsa_aberta("frxEURUSD") is True and h.bolsa_aberta("frxFECHADO") is False
                assert {a["symbol"] for a in lista} == {"frxEURUSD", "frxFECHADO"}
                s = await h.obter_serie("frxEURUSD", 60, 100)
                await asyncio.wait_for(s.pronta.wait(), 10)
                sid = s.sub_id
                h.liberar(s)
                await _esperar(lambda: ("frxEURUSD", 60) not in h.series and fake.contar(forget=sid) == 1)
            finally:
                await h.fechar()
    rodar(cenario())


# --------------------------------------------------------------------------- scanner
def _analise(**k):
    base = {"ok": True, "tendencia": "ALTA", "adx": 30.0, "atr_percentil": 50.0}
    return {**base, **k}


def test_pontuacao_regra_explicita():
    r = scanner.pontuar(_analise(), None, aberto=True)          # ADX 30, percentil 50
    assert r["componentes"] == {"volatilidade": 25.0, "tendencia": 18.8, "estrategia": 0.0}
    assert r["pontos"] == 43.8 and [e["nome"] for e in r["explicacao"]] == ["Movimento", "Tendência", "Estratégia"]
    assert scanner.pontuar(_analise(), None, aberto=False)["elegivel"] is False
    r = scanner.pontuar(_analise(tendencia="LATERAL", atr_percentil=95), None, True)
    assert r["componentes"]["volatilidade"] == 5.0 and r["componentes"]["tendencia"] == 7.5   # lateral = 40%
    assert scanner.pontuar(_analise(adx=15), None, True)["componentes"]["tendencia"] == 0.0
    assert scanner.pontuar(_analise(adx=40), None, True)["componentes"]["tendencia"] == 25.0
    ranking = {"melhor": "x", "break_even": 0.54,
               "linhas": [{"id": "x", "nome": "X", "janela": {"ic_inf": 0.565}}]}  # folga 2,5 p.p. -> +10
    assert scanner.pontuar(_analise(), ranking, True)["componentes"]["estrategia"] == 40.0


def test_pontuacao_diferencia_ativos_parecidos():
    """Antes, quase todo ativo 'normal' empatava em 50. Agora diferenças pequenas aparecem na nota."""
    notas = {scanner.pontuar(_analise(adx=adx, atr_percentil=p), None, True)["pontos"]
             for adx, p in [(26, 50), (28, 50), (26, 30), (31, 85), (22, 60)]}
    assert len(notas) == 5


def test_ordenar_top_com_desempate_explicito():
    res = [{"simbolo": "A", "elegivel": True, "pontos": 50.0, "adx": 20, "atr_percentil": 50},
           {"simbolo": "B", "elegivel": False, "pontos": 0, "adx": 40},
           {"simbolo": "C", "elegivel": True, "pontos": 50.0, "adx": 30, "atr_percentil": 50},
           {"simbolo": "D", "elegivel": True, "pontos": 75.0, "adx": 10, "atr_percentil": 50},
           {"simbolo": "E", "elegivel": True, "pontos": 50.0, "adx": 20, "atr_percentil": 54},
           {"simbolo": "F", "elegivel": True, "pontos": 50.0, "adx": 20, "atr_percentil": 54}]
    assert [r["simbolo"] for r in scanner.ordenar(res)] == ["D", "C", "E", "F", "A", "B"]


def test_avaliar_ativo_real():
    r = scanner.avaliar_ativo("X", df_aleatorio(1500, seed=5), bt.ConfigBacktest(), aberto=True)
    assert r["elegivel"] and 0 <= r["pontos"] <= 100 and r["resumo"]
    assert r["melhor_estrategia"] is None  # passeio aleatório: sem vantagem comprovada
