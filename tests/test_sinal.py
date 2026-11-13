from binarias import sinal


def _linha(id_, acerto, decididas=200, ic_inf=None, vantagem=False):
    return {"id": id_, "nome": id_.upper(), "janela": {
        "acerto": acerto, "ic_inf": ic_inf if ic_inf is not None else acerto - 0.05, "ic_sup": acerto + 0.05,
        "operacoes": decididas, "decididas": decididas, "lucro": 1.0, "vantagem": vantagem}}


def _ranking(melhor="a", linhas=None):
    linhas = linhas or [_linha("a", 0.62, ic_inf=0.56, vantagem=True), _linha("b", 0.57), _linha("c", 0.45)]
    return {"melhor": melhor, "linhas": linhas, "break_even": 0.5405, "janela": 500, "min_ops": 100,
            "confianca": 0.95, "expiracao": 1}


def test_sem_estrategia_com_vantagem():
    d = sinal.decidir(_ranking(melhor=None), {"a": "CALL"}, {})
    assert d["estado"] == "SEM_SINAL" and d["titulo"] == "SEM SINAL CONFIÁVEL NO MOMENTO" and d["dir"] is None


def test_entrar_com_estrategia_do_topo():
    d = sinal.decidir(_ranking(), {"a": "CALL", "b": None, "c": "PUT"}, {})
    assert d["estado"] == "ENTRAR" and d["dir"] == "CALL" and d["estrategia"] == "a"
    # 'c' discorda, mas tem acerto abaixo do break-even -> não conta como conflito


def test_conflito_com_estrategia_relevante():
    d = sinal.decidir(_ranking(), {"a": "CALL", "b": "PUT"}, {})
    assert d["estado"] == "CONFLITO" and d["opostos"] == ["B"] and "NÃO ENTRAR" in d["titulo"]


def test_conflito_ignora_estrategia_desmarcada_ou_com_poucas_ops():
    assert sinal.decidir(_ranking(), {"a": "CALL", "b": "PUT"}, {}, ativas={"a", "c"})["estado"] == "ENTRAR"
    r = _ranking(linhas=[_linha("a", 0.62, ic_inf=0.56, vantagem=True), _linha("b", 0.6, decididas=10)])
    assert sinal.decidir(r, {"a": "PUT", "b": "CALL"}, {})["estado"] == "ENTRAR"


def test_concordancia_listada():
    d = sinal.decidir(_ranking(), {"a": "PUT", "b": "PUT"}, {})
    assert d["estado"] == "ENTRAR" and d["concordam"] == ["B"]


def test_preparando_e_aguardando():
    assert sinal.decidir(_ranking(), {}, {"a": "PUT"})["estado"] == "PREPARANDO"
    assert sinal.decidir(_ranking(), {}, {"b": "PUT"})["estado"] == "AGUARDANDO"


def test_previa_nunca_gera_entrada():
    d = sinal.decidir(_ranking(), {"a": "CALL"}, {}, previa=True)
    assert d["estado"] == "PREPARANDO" and d["dir"] == "CALL"


def test_melhor_desmarcada_vira_sem_sinal():
    assert sinal.decidir(_ranking(), {"a": "CALL"}, {}, ativas={"b"})["estado"] == "SEM_SINAL"
