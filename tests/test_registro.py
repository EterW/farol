"""Registro dos sinais ao vivo: PENDENTE em vez de CANCELADO, conversão do arquivo antigo e reconciliação."""

import csv
import time

import pandas as pd
from fake_deriv import FakeDeriv, preco
from test_hub_scanner import _esperar, rodar
from test_sessao import NavFalso

from binarias import hub as hubmod
from binarias import registro as regmod
from binarias import sessao as sessmod
from binarias.registro import COLUNAS_ANTIGAS, COLUNAS_CSV, Registro, fmt_data, reconciliar


def _linha(t_sinal: int, ativo="frxEURUSD", tf="M1", seg=60, est="Engolfo", d="CALL", **extra) -> dict:
    return {
        "data_sinal": fmt_data(t_sinal),
        "data_entrada": fmt_data(t_sinal + seg),
        "ativo": ativo,
        "timeframe": tf,
        "estrategia": est,
        "direcao": d,
        "expiracao": 1,
        "resultado": "PENDENTE",
        **extra,
    }


def test_arquivo_antigo_e_convertido_com_backup_sem_perder_linhas(tmp_path):
    caminho = tmp_path / "sinais.csv"
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_ANTIGAS)
        w.writeheader()
        base = {"data_sinal": "2026-11-12 03:34:00", "data_entrada": "2026-11-12 03:35:00", "ativo": "frxEURUSD"}
        base |= {"timeframe": "M1", "principal": "não", "expiracao": 1, "preco_entrada": "", "preco_saida": ""}
        w.writerow({**base, "estrategia": "Seguir cor", "direcao": "PUT", "resultado": "CANCELADO"})
        w.writerow({**base, "estrategia": "Engolfo", "direcao": "PUT", "resultado": "CANCELADO"})
        w.writerow({**base, "estrategia": "MHI 1 (minoria)", "direcao": "CALL", "resultado": "WIN"})
    reg = Registro(str(caminho), str(tmp_path / "backups"))
    resumo = reg.migrar()
    assert resumo["convertido"] and resumo["linhas"] == 3 and resumo["reabertas"] == 2
    copias = list((tmp_path / "backups").glob("*.csv"))
    assert len(copias) == 1 and "Seguir cor" in copias[0].read_text(encoding="utf-8-sig")
    linhas = reg.ler()
    assert len(linhas) == 3 and list(linhas[0]) == COLUNAS_CSV
    assert [l["resultado"] for l in linhas] == ["PENDENTE", "PENDENTE", "WIN"]
    assert linhas[0]["motivo"] == regmod.MOTIVO_ANTIGO
    assert {l["evento_id"] for l in linhas} == {"frxEURUSD|M1|" + str(regmod.epoch_de("2026-11-12 03:34:00"))}
    assert [l["n_estrategias_no_evento"] for l in linhas] == ["3", "3", "3"]
    assert [l["concordancia"] for l in linhas] == ["2", "2", "1"]  # 2 PUT, 1 CALL
    assert linhas[0]["controle"] == "sim" and linhas[1]["controle"] == "não"
    assert not reg.migrar()["convertido"], "converter de novo não faz nada"


def test_atualizar_so_mexe_em_pendente_e_e_idempotente(tmp_path):
    reg = Registro(str(tmp_path / "s.csv"), str(tmp_path / "b"))
    reg.adicionar([_linha(1_700_000_040, id="a"), _linha(1_700_000_040, id="b", d="PUT")])
    assert reg.atualizar({"a": {"resultado": "WIN", "preco_entrada": 1.0, "preco_saida": 2.0}}) == 1
    assert reg.atualizar({"a": {"resultado": "LOSS"}}) == 0, "linha resolvida não muda mais"
    por_id = {l["id"]: l for l in reg.ler()}
    assert por_id["a"]["resultado"] == "WIN" and por_id["a"]["resolvido_em"]
    assert por_id["b"]["resultado"] == "PENDENTE" and len(reg.pendentes()) == 1


def test_reconciliacao_resolve_com_os_precos_da_deriv_e_cancela_so_sem_dados(tmp_path):
    reg = Registro(str(tmp_path / "s.csv"), str(tmp_path / "b"))
    agora = int(time.time())
    t = agora - agora % 60 - 600  # vela do sinal 10 min atrás (entrada e saída já fecharam)
    t5 = agora - agora % 300 - 1800
    reg.adicionar(
        [
            _linha(t, id="m1"),
            _linha(t, id="m1p", d="PUT", est="Seguir cor"),
            _linha(t5, id="m5", tf="M5", seg=300, ativo="frxGBPUSD"),
            _linha(t + 7, id="torta"),  # vela desalinhada: a Deriv nunca terá essa vela -> CANCELADO
            _linha(agora - agora % 60, id="futuro"),  # ainda não venceu: continua PENDENTE
        ]
    )

    async def cenario():
        async with FakeDeriv() as fake:
            h = hubmod.DerivHub(fake.url, intervalo=0)
            h.iniciar()
            try:
                await _esperar(h.conectado.is_set)
                return await reconciliar(reg, h.pedir, h.agora())
            finally:
                await h.fechar()

    resumo = rodar(cenario())
    assert resumo["resolvidas"] == 3 and resumo["canceladas"] == 1
    por_id = {l["id"]: l for l in reg.ler()}
    e = t + 60
    assert float(por_id["m1"]["preco_entrada"]) == preco("frxEURUSD", e)
    assert float(por_id["m1"]["preco_saida"]) == preco("frxEURUSD", e + 30)  # fechamento da vela no Deriv falso
    esperado = "WIN" if preco("frxEURUSD", e + 30) > preco("frxEURUSD", e) else "LOSS"
    assert por_id["m1"]["resultado"] == esperado
    assert por_id["m1p"]["resultado"] == ("LOSS" if esperado == "WIN" else "WIN")
    assert float(por_id["m5"]["preco_entrada"]) == preco("frxGBPUSD", t5 + 300)
    assert all(por_id[k]["resolucao"] == "reconciliacao" for k in ("m1", "m5", "torta"))
    assert por_id["m1"]["motivo"] == regmod.TEXTO_RECONCILIADO
    assert por_id["torta"]["resultado"] == "CANCELADO" and "não tem mais a vela" in por_id["torta"]["motivo"]
    assert por_id["futuro"]["resultado"] == "PENDENTE"


def test_reconciliacao_sem_conexao_deixa_pendente(tmp_path):
    reg = Registro(str(tmp_path / "s.csv"), str(tmp_path / "b"))
    reg.adicionar([_linha(int(time.time()) // 60 * 60 - 600, id="x")])

    async def pedir_falha(_payload):
        raise regmod.ConexaoPerdida()

    resumo = rodar(reconciliar(reg, pedir_falha, time.time()))
    assert resumo["erros"] == 1 and reg.pendentes()[0]["id"] == "x"


def test_sinal_troca_de_ativo_fecha_e_reabre_resolvido(monkeypatch, tmp_path):
    """Ponta a ponta com o Deriv falso: sinal gravado PENDENTE -> troca de ativo (não cancela) -> servidor
    fechado -> nova conexão (o Farol reaberto) -> reconciliação com os preços corretos."""
    monkeypatch.setattr(sessmod, "N_HISTORICO", 300)
    monkeypatch.setattr(sessmod, "ATIVOS_SCANNER", ["frxEURUSD"])
    reg = Registro(str(tmp_path / "sinais.csv"), str(tmp_path / "b"))
    monkeypatch.setattr(sessmod, "registro", reg)
    monkeypatch.setattr(hubmod, "ESPERA_LIBERAR", 0.1)

    async def primeira_execucao():
        async with FakeDeriv() as fake:
            h = hubmod.DerivHub(fake.url, intervalo=0)
            h.iniciar()
            nav = NavFalso()
            s = sessmod.Sessao(nav, h)
            try:
                await s.iniciar("frxEURUSD", "M1", 1, 0.85)
                await _esperar(lambda: "decisao" in nav.tipos(), timeout=30)
                # força uma vela "fechada" no passado com sinal de duas estratégias (caminho real de _ao_fechar)
                agora = h.agora()
                s.df = s.df[s.df["epoch"] <= agora - 300].reset_index(drop=True)
                ranking = {**s.ranking, "linhas": [dict(l) for l in s.ranking["linhas"]]}
                for l in ranking["linhas"]:
                    l["sinal"] = {"engolfo": "CALL", "rsi_reversao": "PUT"}.get(l["id"])
                monkeypatch.setattr(s, "_calcular", lambda *_a, **_k: (ranking, s.analise))
                await s._ao_fechar(pd.DataFrame(columns=["epoch", "open", "high", "low", "close"]), 1)
                linhas = reg.ler()
                assert len(linhas) == 2 and {l["resultado"] for l in linhas} == {"PENDENTE"}
                assert linhas[0]["n_estrategias_no_evento"] == "2" and linhas[0]["concordancia"] == "1"
                assert linhas[0]["latencia_ms"] and linhas[0]["preco_aviso"] and linhas[0]["estado_veredito"]
                await s.iniciar("frxGBPUSD", "M1", 1, 0.85)  # troca de ativo antes da expiração
                assert {l["resultado"] for l in reg.ler()} == {"PENDENTE"}, "trocar de ativo não cancela mais"
                return linhas
            finally:
                await s.parar()
                await h.fechar()  # "fecha o servidor"

    linhas = rodar(primeira_execucao(), timeout=90)
    assert {l["resultado"] for l in reg.ler()} == {"PENDENTE"}

    async def reabrir():
        async with FakeDeriv() as fake:
            h = hubmod.DerivHub(fake.url, intervalo=0)
            h.iniciar()
            try:
                await _esperar(h.conectado.is_set)
                return await reconciliar(reg, h.pedir, h.agora())
            finally:
                await h.fechar()

    resumo = rodar(reabrir())
    assert resumo["resolvidas"] == 2
    t_ent = regmod.epoch_de(linhas[0]["data_entrada"])
    for l in reg.ler():
        assert l["resultado"] in ("WIN", "LOSS", "EMPATE") and l["resolucao"] == "reconciliacao"
        assert float(l["preco_entrada"]) == preco("frxEURUSD", t_ent)
        assert float(l["preco_saida"]) == preco("frxEURUSD", t_ent + 30)
