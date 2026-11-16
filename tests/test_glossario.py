"""Modo educativo: glossário com 2 frases + exemplo por termo, sem promessa."""

import re

from binarias import glossario as G

PROMESSA = [r"garantid", r"88\s*%", r"vai ganhar", r"lucro certo", r"sem risco", r"assertividade", r"vai subir"]


def _frases(texto):
    return [f for f in re.split(r"(?<=[.!?])\s+", texto.strip()) if f]


def test_cada_termo_tem_duas_frases_e_um_exemplo():
    for t in G.GLOSSARIO:
        assert len(_frases(t["texto"])) == 2, t["termo"]
        assert t["exemplo"].strip(), t["termo"]


def test_termos_pedidos_estao_no_glossario():
    termos = {t["termo"].lower() for t in G.GLOSSARIO}
    for pedido in ("break-even", "intervalo de confiança", "walk-forward", "adx", "atr", "macd", "rsi"):
        assert any(pedido in t for t in termos), pedido
    assert len(termos) == len(G.GLOSSARIO), "termo repetido"


def test_sem_promessa():
    textos = [x for t in G.GLOSSARIO for x in t.values()] + [x for s in G.SILENCIO for x in s.values()]
    for texto in textos:
        for padrao in PROMESSA:
            assert not re.search(padrao, texto.lower()), (padrao, texto)


def test_tour_do_silencio_explica_os_motivos():
    texto = " ".join(s["texto"] for s in G.SILENCIO).lower()
    for motivo in ("operações", "break-even", "holm", "conflito", "limite"):
        assert motivo in texto, motivo
