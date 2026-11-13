"""Regras de honestidade do veredito (tela principal) e da linguagem simples."""
import itertools
import os
import random
import re

import pytest

from binarias import demo, mercado, ranking as rk, scanner, sinal, veredito
from binarias.estatistica import wilson
from conftest import df_aleatorio

BE = 1 / 1.85
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _linha(id_, wins, n, min_ops=100, forca="estável"):
    inf, sup = wilson(wins, n) if n else (None, None)
    jan = {"acerto": wins / n if n else None, "ic_inf": inf, "ic_sup": sup, "operacoes": n, "decididas": n,
           "wins": wins, "lucro": 0.0, "vantagem": bool(n >= min_ops and inf is not None and inf > BE)}
    f = {"estado": forca, "z": None}
    return {"id": id_, "nome": id_.upper(), "janela": jan, "forca": f, "selo": rk.selo(jan, f, min_ops)}


def _ranking(linhas):
    linhas = sorted(linhas, key=lambda l: (0 if l["janela"]["vantagem"] else 1, -(l["janela"]["ic_inf"] or 0)))
    melhor = next((l["id"] for l in linhas if l["janela"]["vantagem"]), None)
    return {"linhas": linhas, "melhor": melhor, "break_even": BE, "janela": 500, "min_ops": 100,
            "confianca": 0.95, "expiracao": 1, "payout": 0.85}


# --------------------------------------------------------------------------- ENTRAR só com vantagem comprovada
def test_entrar_exige_vantagem_comprovada_em_qualquer_combinacao():
    rnd = random.Random(42)
    vistos = set()
    for _ in range(400):
        linhas = []
        for k in range(4):
            n = rnd.choice([0, 20, 60, 99, 100, 150, 300])
            wins = int(n * rnd.uniform(0.4, 0.7))
            linhas.append(_linha(f"e{k}", wins, n))
        r = _ranking(linhas)
        sinais = {l["id"]: rnd.choice([None, "CALL", "PUT"]) for l in linhas}
        preparo = {l["id"]: rnd.choice([None, "CALL", "PUT"]) for l in linhas}
        obs = rnd.random() < 0.5
        for previa in (False, True):
            dec = sinal.decidir(r, sinais, preparo, previa=previa)
            v = veredito.montar(dec, r, None, obs, {k: {"estado": "SINAL", "dir": d} for k, d in sinais.items()})
            vistos.add(v["estado"])
            if v["estado"] in ("ENTRAR", "PREPARANDO", "CONFLITO"):
                linha = next(l for l in r["linhas"] if l["id"] == v["estrategia"])
                assert linha["janela"]["decididas"] >= 100 and linha["janela"]["ic_inf"] > BE
                assert v["comprovada"] is True
            if v["som"] == "entrada":
                assert v["estado"] == "ENTRAR"
            if v["estado"] == "OBSERVACAO":
                assert obs and r["melhor"] is None and v["som"] is None and not v["comprovada"]
    assert {"ENTRAR", "PREPARANDO", "AGUARDAR", "CONFLITO", "OBSERVACAO"} <= vistos


def test_decisao_entrar_forjada_sem_vantagem_vira_aguardar():
    r = _ranking([_linha("a", 70, 120)])   # 58% mas IC inclui o break-even
    assert r["melhor"] is None
    forjada = {"estado": "ENTRAR", "dir": "CALL", "estrategia": "a", "nome": "A", "titulo": "ENTRAR"}
    v = veredito.montar(forjada, r)
    assert v["estado"] == "AGUARDAR" and v["som"] is None and v["dir"] is None


def test_poucas_operacoes_nunca_comprova_mesmo_com_acerto_alto():
    r = _ranking([_linha("a", 80, 99)])    # 81% em 99 ops: abaixo do mínimo
    assert r["melhor"] is None
    v = veredito.montar(sinal.decidir(r, {"a": "CALL"}, {}), r)
    assert v["estado"] == "AGUARDAR"


def test_observacao_mostra_candidata_rotulada_e_sem_som():
    r = _ranking([_linha("a", 60, 110), _linha("b", 30, 70)])
    dec = sinal.decidir(r, {"a": "PUT"}, {})
    desligado = veredito.montar(dec, r, None, observacao=False)
    assert desligado["estado"] == "AGUARDAR" and "modo observação" in desligado["frase"]
    v = veredito.montar(dec, r, None, observacao=True, estados={"a": {"estado": "SINAL", "dir": "PUT"}})
    assert v["estado"] == "OBSERVACAO" and v["estrategia"] == "a" and v["dir"] == "PUT"
    assert "NÃO COMPROVADA" in v["rotulo"] and "não é recomendação" in v["rotulo"]
    assert v["som"] is None and v["comprovada"] is False
    assert "entre" in v["prob"]["texto"] and v["prob"]["n"] == 110


def test_motivo_do_aguardar_usa_o_mercado():
    r = _ranking([_linha("a", 50, 110)])
    dec = sinal.decidir(r, {}, {})
    v = veredito.montar(dec, r, {"ok": True, "lateral": True, "movimento": "Normal"})
    assert v["frase"].startswith("Mercado lateral e nenhuma estratégia com vantagem comprovada")


def test_veredito_de_cada_estado_tem_titulo_e_frase():
    r = _ranking([_linha("a", 200, 320), _linha("b", 80, 140)])
    casos = {"ENTRAR": ({"a": "CALL"}, {}), "CONFLITO": ({"a": "CALL", "b": "PUT"}, {}),
             "PREPARANDO": ({}, {"a": "PUT"}), "AGUARDAR": ({}, {})}
    for esperado, (s, p) in casos.items():
        v = veredito.montar(sinal.decidir(r, s, p), r)
        assert v["estado"] == esperado and v["titulo"] and v["frase"]
        assert v["prob"] and "entre" in v["prob"]["texto"]
    assert veredito.montar(sinal.decidir(r, {"a": "CALL"}, {}), r)["acao"] == "COMPRA"


# --------------------------------------------------------------------------- texto de probabilidade
@pytest.mark.parametrize("wins,n", [(57, 100), (200, 320), (12, 20), (1, 1), (99, 100), (0, 150)])
def test_probabilidade_sempre_tem_intervalo_amostra_e_break_even(wins, n):
    inf, sup = wilson(wins, n)
    p = veredito.texto_probabilidade({"acerto": wins / n, "ic_inf": inf, "ic_sup": sup, "decididas": n}, BE, 100, 500)
    assert p["texto"].startswith("Probabilidade estimada:")
    assert re.search(r"\(entre [\d,]+% e [\d,]+%\)", p["texto"])
    assert f"{n} operações" in p["amostra"]
    assert "54,1%" in p["break_even_txt"]
    assert p["poucos_dados"] == (n < 100)
    assert p["pode_nao_ter_vantagem"] == (inf <= BE)
    codigos = {a["codigo"] for a in p["avisos"]}
    assert ("poucos" in codigos) == (n < 100) and ("sem_vantagem" in codigos) == (inf <= BE)


def test_probabilidade_sem_dados_nao_inventa_numero():
    p = veredito.texto_probabilidade({"acerto": None, "ic_inf": None, "ic_sup": None, "decididas": 0}, BE, 100)
    assert not p["ok"] and p["acerto"] is None and "sem dados" in p["texto"] and "%" not in p["texto"]


def test_probabilidade_usa_decimal_quando_arredondamento_esconderia_o_break_even():
    p = veredito.texto_probabilidade({"acerto": 0.58, "ic_inf": 0.5440, "ic_sup": 0.61, "decididas": 700}, BE, 100)
    assert "54,4%" in p["texto"]


# --------------------------------------------------------------------------- selos do ranking
def test_selos():
    assert rk.selo(_linha("a", 200, 320)["janela"], None)["codigo"] == "comprovada"
    assert rk.selo(_linha("a", 30, 50)["janela"], None)["codigo"] == "poucos"
    assert rk.selo(_linha("a", 55, 110)["janela"], None)["codigo"] == "sem"
    assert rk.selo(_linha("a", 55, 110)["janela"], {"estado": "perdendo força"})["codigo"] == "perdendo"
    assert rk.selo(None, None)["texto"] == "Poucos dados"
    s = rk.selo(_linha("a", 200, 320)["janela"], {"estado": "perdendo força"})
    assert s["codigo"] == "comprovada" and s["perdendo_forca"]


def test_ranking_real_tem_selo_em_todas_as_linhas(aleatorio):
    from binarias.backtest import ConfigBacktest
    r = rk.calcular_ranking(aleatorio, ConfigBacktest())
    assert all(l["selo"]["texto"] in rk.SELOS.values() for l in r["linhas"])


# --------------------------------------------------------------------------- mercado e top 3 em linguagem simples
def test_mercado_humano_sem_jargao():
    a = mercado.analisar(df_aleatorio(800, seed=2, tendencia=0.02))
    h = a["humano"]
    assert h["tendencia"] in ("SUBINDO", "DESCENDO", "LATERAL")
    assert h["forca"] in ("Fraca", "Média", "Forte") and h["movimento"] in ("Calmo", "Normal", "Agitado")
    assert h["vela"] in ("subindo", "descendo", "parada")
    for jargao in ("ADX", "ATR", "percentil", "MM50", "média de 50"):
        assert jargao not in h["frase"]
    assert mercado.movimento_humano("muito alta") == "Agitado" and mercado.movimento_humano("baixa") == "Calmo"
    assert not mercado.humano({"ok": False, "motivo": "x"})["ok"]


def test_top3_tem_spark_e_porque():
    from binarias.backtest import ConfigBacktest
    r = scanner.avaliar_ativo("X", df_aleatorio(700, seed=5), ConfigBacktest(), aberto=True)
    assert len(r["spark"]) == scanner.N_SPARK and r["porque"]
    assert "ADX" not in r["porque"] and "ATR" not in r["porque"]
    fechado = scanner.avaliar_ativo("X", df_aleatorio(700, seed=5), ConfigBacktest(), aberto=False)
    assert fechado["porque"] == "mercado fechado"


# --------------------------------------------------------------------------- demonstração
def test_cenarios_de_demonstracao_forcam_cada_estado():
    esperado = {"entrar": "ENTRAR", "preparando": "PREPARANDO", "aguardar": "AGUARDAR",
                "conflito": "CONFLITO", "observacao": "OBSERVACAO"}
    for cenario, estado in esperado.items():
        msgs = demo.mensagens(cenario)
        tipos = [m["tipo"] for m in msgs]
        assert {"historico", "ranking", "analise", "estado", "top3", "decisao"} <= set(tipos)
        v = next(m for m in msgs if m["tipo"] == "estado")["veredito"]
        assert v["estado"] == estado
    with pytest.raises(ValueError):
        demo.mensagens("inexistente")


# --------------------------------------------------------------------------- nada de promessa na interface
PROIBIDOS = [r"garantid", r"88\s*%", r"vai ganhar", r"lucro certo", r"sem risco", r"100\s*%\s*de acerto"]


def test_interface_nao_promete_resultado():
    arquivos = [os.path.join(RAIZ, "static", f) for f in os.listdir(os.path.join(RAIZ, "static"))
                if f.endswith((".html", ".js", ".css"))]
    assert arquivos
    for caminho in arquivos:
        texto = open(caminho, encoding="utf-8").read().lower()
        for padrao in PROIBIDOS:
            if caminho.endswith(".css") and padrao[0].isdigit():
                continue   # no CSS, "88%" é cor/tamanho, não texto da tela
            assert not re.search(padrao, texto), f"'{padrao}' em {caminho}"
    # e nos textos que o servidor gera para a tela
    for cenario in demo.CENARIOS:
        texto = str(demo.mensagens(cenario)).lower()
        for padrao in PROIBIDOS:
            assert not re.search(padrao, texto), f"'{padrao}' no cenário {cenario}"


def test_aviso_de_risco_sempre_presente():
    html = open(os.path.join(RAIZ, "static", "index.html"), encoding="utf-8").read()
    assert "Nenhum sinal é garantia" in html and "perda total" in html
