"""Avisos do Farol: só a líder avisa, conflito bloqueia, sem vantagem = silêncio, uma vez por vela,
histerese na troca de líder, progresso de formação objetivo e ordem honesta do ranking."""
import pandas as pd
import pytest

from binarias import avisos, progresso, ranking as rk, sinal, veredito
from binarias.avisos import MotorAvisos, SeletorLider
from binarias.estatistica import wilson
from binarias.estrategias import ESTRATEGIAS, POR_ID
from conftest import df_aleatorio, df_de_ohlc

BE = 1 / 1.85


def _linha(id_, wins, n, min_ops=100):
    inf, sup = wilson(wins, n) if n else (None, None)
    jan = {"acerto": wins / n if n else None, "ic_inf": inf, "ic_sup": sup, "operacoes": n, "decididas": n,
           "wins": wins, "lucro": 0.0, "vantagem": bool(n >= min_ops and inf is not None and inf > BE)}
    return {"id": id_, "nome": id_.upper(), "janela": jan, "forca": None, "selo": rk.selo(jan, None, min_ops)}


def _ranking(linhas):
    linhas = sorted(linhas, key=rk.chave_ordem)
    melhor = next((x["id"] for x in linhas if x["janela"]["vantagem"]), None)
    return {"linhas": linhas, "melhor": melhor, "break_even": BE, "janela": 1500, "min_ops": 100,
            "confianca": 0.95, "expiracao": 1, "payout": 0.85}


def _prog(id_, pct, direcao="CALL"):
    return {"id": id_, "pct": pct, "dir": direcao, "cumpridas": 2, "total": 3}


def _rodada(r, sinais, lider, observacao=False, motor=None, vela=1000):
    """Fechamento de uma vela: decisão + veredito + avisos (como a sessão faz)."""
    motor = motor or MotorAvisos()
    dec = sinal.decidir(r, sinais, {}, lider=lider)
    ver = veredito.montar(dec, r, None, observacao, {k: {"estado": "SINAL", "dir": d} for k, d in sinais.items() if d})
    return ver, motor.fechamento(ver, vela, "EUR/USD")


def _formacao(r, lider, prog, observacao=False, motor=None, vela=1000):
    motor = motor or MotorAvisos()
    formando = {lider: prog["dir"]} if lider and prog["id"] == lider and prog["pct"] >= motor.limite else {}
    dec = sinal.decidir(r, {}, formando, previa=True, lider=lider)
    estados = {prog["id"]: {"estado": "FORMANDO" if prog["pct"] >= motor.limite else "PARCIAL", "dir": prog["dir"]}}
    ver = veredito.montar(dec, r, None, observacao, estados, None, prog)
    return ver, motor.formacao(ver, prog, vela, "EUR/USD")


# --------------------------------------------------------------------------- só a líder avisa
def test_so_a_lider_gera_aviso_de_entrada():
    r = _ranking([_linha("a", 210, 320), _linha("b", 200, 320)])   # duas comprovadas; "a" é a líder
    sel = SeletorLider()
    assert sel.atualizar(r)["lider"] == "a"
    _, av = _rodada(r, {"b": "CALL"}, sel.atual)                 # só a outra deu sinal
    assert not [a for a in av if a["notificar"] or a["som"]]
    ver, av = _rodada(r, {"a": "PUT", "b": "PUT"}, sel.atual)   # a líder deu sinal (b concorda)
    entradas = [a for a in av if a["categoria"] == "entrada"]
    assert ver["estado"] == "ENTRAR" and len(entradas) == 1
    e = entradas[0]
    assert e["som"] == "entrada_put" and e["notificar"] and e["dir"] == "PUT"
    assert e["texto"].startswith("Entre AGORA: VENDA ▼ em EUR/USD, expiração 1 vela.")
    assert "Probabilidade estimada" in e["texto"] and "320 operações" in e["texto"] and "entre" in e["texto"]


def test_formacao_so_da_lider_e_acima_do_limite():
    r = _ranking([_linha("a", 210, 320), _linha("b", 200, 320)])
    _, av = _formacao(r, "a", _prog("b", 95))          # quem está se formando é a outra
    assert av == []
    _, av = _formacao(r, "a", _prog("a", 60))          # líder abaixo do limite (70)
    assert av == []
    ver, av = _formacao(r, "a", _prog("a", 78))
    assert ver["estado"] == "PREPARANDO" and ver["progresso"]["pct"] == 78
    assert len(av) == 1 and av[0]["categoria"] == "formando" and av[0]["som"] == "formando"
    assert av[0]["texto"].startswith("Farol: A está se formando em EUR/USD")
    assert "Fique atento: o sinal pode sair na próxima vela." in av[0]["texto"]


def test_limite_de_formacao_configuravel():
    r = _ranking([_linha("a", 210, 320)])
    m = MotorAvisos(limite=90)
    assert _formacao(r, "a", _prog("a", 85), motor=m)[1] == []
    assert len(_formacao(r, "a", _prog("a", 92), motor=m)[1]) == 1


# --------------------------------------------------------------------------- conflito
def test_conflito_bloqueia_a_entrada():
    r = _ranking([_linha("a", 210, 320), _linha("b", 85, 150)])   # b: ≥ 30 ops e acerto acima do break-even
    ver, av = _rodada(r, {"a": "CALL", "b": "PUT"}, "a")
    assert ver["estado"] == "CONFLITO" and ver["titulo"] == "CONFLITO, NÃO ENTRAR"
    assert not [a for a in av if a["categoria"] == "entrada"]
    conf = [a for a in av if a["categoria"] == "conflito"]
    assert len(conf) == 1 and conf[0]["som"] is None and not conf[0]["notificar"]


# --------------------------------------------------------------------------- sem vantagem comprovada
@pytest.mark.parametrize("observacao", [False, True])
def test_sem_vantagem_comprovada_nenhum_aviso_de_entrada_nem_formacao(observacao):
    r = _ranking([_linha("a", 70, 120), _linha("b", 80, 99)])      # 58% (IC inclui BE) e 81% com 99 ops
    sel = SeletorLider()
    assert sel.atualizar(r)["lider"] is None
    m = MotorAvisos()
    for vela in range(5):
        _, av1 = _rodada(r, {"a": "CALL", "b": "CALL"}, sel.atual, observacao, m, vela)
        _, av2 = _formacao(r, sel.atual, _prog("a", 100), observacao, m, vela)
        assert av1 == [] and av2 == []


def test_candidata_nao_comprovada_so_avisa_com_a_opcao_e_rotulada():
    r = _ranking([_linha("a", 70, 120)])
    m = MotorAvisos(avisar_obs=True)
    ver, av = _formacao(r, None, _prog("a", 90, "PUT"), observacao=True, motor=m)
    assert ver["estado"] == "OBSERVACAO" and "NÃO COMPROVADA" in ver["rotulo"]
    assert len(av) == 1 and av[0]["categoria"] == "observacao" and av[0]["som"] == "observacao"
    assert "OBSERVAÇÃO, sem vantagem comprovada" in av[0]["texto"] and "OBSERVAÇÃO" in av[0]["titulo"]
    _, av = _rodada(r, {"a": "PUT"}, None, True, m, vela=2000)
    assert [a["categoria"] for a in av] == ["observacao"]
    assert MotorAvisos.__dataclass_fields__["avisar_obs"].default is False   # desligado por padrão


# --------------------------------------------------------------------------- uma vez por vela
def test_nao_repete_aviso_na_mesma_vela():
    r = _ranking([_linha("a", 210, 320)])
    m = MotorAvisos()
    total = [a for _ in range(5) for a in _formacao(r, "a", _prog("a", 80), motor=m, vela=1000)[1]]
    assert len(total) == 1
    assert len(_formacao(r, "a", _prog("a", 80), motor=m, vela=1060)[1]) == 1      # vela nova: avisa de novo
    entradas = [a for _ in range(3) for a in _rodada(r, {"a": "CALL"}, "a", motor=m, vela=1120)[1]]
    assert len(entradas) == 1
    # na vela da entrada não há aviso de formação (evita "Entre agora" seguido de "se formando")
    assert _formacao(r, "a", _prog("a", 90), motor=m, vela=1120)[1] == []


def test_resultado_com_placar_so_da_entrada_avisada():
    m = MotorAvisos()
    assert m.resultado({"principal": False, "nome": "X"}, "WIN", "EUR/USD") == []
    m.resultado({"principal": True, "nome": "X"}, "WIN", "EUR/USD")
    (a,) = m.resultado({"principal": True, "nome": "X"}, "LOSS", "EUR/USD")
    assert a["categoria"] == "resultado" and a["som"] == "resultado" and a["notificar"]
    assert "Placar da sessão: 1 WIN · 1 LOSS · 0 EMPATE" in a["texto"]


# --------------------------------------------------------------------------- histerese da líder
def test_histerese_evita_troca_a_cada_vela():
    a_fraca, b_forte = _linha("a", 205, 320), _linha("b", 207, 320)    # diferença < 2 p.p.
    r_b = _ranking([a_fraca, b_forte])
    r_a = _ranking([_linha("a", 208, 320), _linha("b", 206, 320)])
    sel = SeletorLider()
    sel.atualizar(r_a)
    assert sel.atual == "a"
    trocas = 0
    for k in range(10):                     # topo alterna a cada vela: a líder NÃO troca
        trocas += sel.atualizar(r_b if k % 2 == 0 else r_a)["trocou"]
    assert sel.atual == "a" and trocas == 0
    for k in range(3):                      # b no topo por 3 velas seguidas: troca na 3ª
        res = sel.atualizar(r_b)
        assert res["trocou"] == (k == 2)
    assert sel.atual == "b"


def test_histerese_troca_na_hora_com_diferenca_grande_ou_lider_invalida():
    sel = SeletorLider()
    sel.atualizar(_ranking([_linha("a", 200, 320), _linha("b", 190, 320)]))
    assert sel.atual == "a"
    res = sel.atualizar(_ranking([_linha("a", 200, 320), _linha("b", 230, 320)]))   # b muito melhor
    assert res["trocou"] and sel.atual == "b"
    res = sel.atualizar(_ranking([_linha("a", 200, 320), _linha("b", 150, 320)]))   # b perdeu a vantagem
    assert res["trocou"] and sel.atual == "a"
    res = sel.atualizar(_ranking([_linha("a", 200, 320)]), ativas={"b"}, contar=False)  # a desmarcada
    assert res["trocou"] and sel.atual is None


def test_troca_de_lider_avisa_sem_som():
    m = MotorAvisos()
    (a,) = m.fechamento({}, 1, "EUR/USD", {"trocou": True, "lider": "x", "anterior": "y"}, {"x": "Engolfo"})
    assert a["categoria"] == "lider" and a["texto"] == "Líder agora: Engolfo"
    assert a["som"] is None and not a["notificar"]


def test_exemplos_do_testar_alertas_cobrem_os_3_tipos():
    cats = {a["categoria"] for a in avisos.exemplos()}
    sons = {a["som"] for a in avisos.exemplos()}
    assert {"formando", "entrada", "resultado"} <= cats
    assert {"entrada_call", "entrada_put"} <= sons


# --------------------------------------------------------------------------- progresso de formação
def test_formula_do_progresso():
    assert progresso.pontuar(3, 3, None) == 100
    assert progresso.pontuar(0, 3, None) == 0
    assert progresso.pontuar(2, 3, None) == 40          # 60% × 2/3
    assert progresso.pontuar(2, 3, 0.5) == 60           # + 40% × (1 − 0,5)
    assert progresso.pontuar(1, 1, 5.0) == 100          # tudo cumprido = 100, qualquer distância


@pytest.mark.parametrize("est", ESTRATEGIAS, ids=[e.id for e in ESTRATEGIAS])
def test_progresso_100_se_e_somente_se_o_sinal_sairia(est):
    df = df_aleatorio(500, seed=21)
    for fim in range(300, 500, 23):
        parcial = df.iloc[:fim]
        p = progresso.calcular(est, parcial)
        s = est.gerar_sinais(parcial).iloc[-1]
        assert 0 <= p["pct"] <= 100 and p["explicacao"]
        assert (p["pct"] == 100) == (s in ("CALL", "PUT"))
        if s in ("CALL", "PUT"):
            assert p["dir"] == s


def test_distancia_ate_o_gatilho_em_atr():
    linhas = [(100.0, 100.5, 99.5, 100.0)] * 30                 # máxima das 20 anteriores = 100,5
    linhas.append((100.0, 100.3, 99.9, 100.2))                  # fecha 0,3 abaixo do rompimento
    p = progresso.calcular(POR_ID["rompimento_sr"], df_de_ohlc(linhas))
    assert p["dir"] == "CALL" and p["cumpridas"] == 0 and p["distancia_atr"] is not None
    assert 0 < p["distancia_atr"] <= 1 and 0 < p["pct"] < 40


# --------------------------------------------------------------------------- ordem honesta do ranking
def test_ranking_ordena_por_status_e_limite_inferior_nunca_pelo_percentual():
    r = _ranking([_linha("muitas", 130, 250), _linha("pequena", 9, 14), _linha("comprovada", 200, 320),
                  _linha("vazia", 0, 0), _linha("media", 60, 110)])
    ids = [x["id"] for x in r["linhas"]]
    assert ids[0] == "comprovada"
    assert ids.index("pequena") > ids.index("media") and ids.index("pequena") > ids.index("muitas")  # 64% com 14 ops
    assert ids[-1] == "vazia"
    pequena = next(x for x in r["linhas"] if x["id"] == "pequena")
    assert pequena["selo"]["codigo"] == "poucos" and pequena["selo"]["amostra_pequena"]


def test_desempate_explicito_por_operacoes_e_nome():
    a = {"id": "a", "nome": "B", "janela": {"decididas": 200, "ic_inf": 0.5, "vantagem": False}}
    b = {"id": "b", "nome": "A", "janela": {"decididas": 300, "ic_inf": 0.5, "vantagem": False}}
    c = {"id": "c", "nome": "A", "janela": {"decididas": 200, "ic_inf": 0.5, "vantagem": False}}
    assert [x["id"] for x in sorted([a, b, c], key=rk.chave_ordem)] == ["b", "c", "a"]


def test_ranking_real_esta_na_ordem_declarada():
    from binarias.backtest import ConfigBacktest
    r = rk.calcular_ranking(df_aleatorio(3000, seed=4), ConfigBacktest())
    assert [rk.chave_ordem(x) for x in r["linhas"]] == sorted(rk.chave_ordem(x) for x in r["linhas"])
    assert pd.Series([rk.status(x) for x in r["linhas"]]).is_monotonic_increasing
