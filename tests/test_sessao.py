"""Integração: sessão ao vivo completa (ativo + scanner) contra o Deriv falso."""

import json

from fake_deriv import FakeDeriv
from test_hub_scanner import _esperar, rodar

from binarias import hub as hubmod
from binarias import sessao as sessmod


class NavFalso:
    def __init__(self):
        self.msgs: list[dict] = []

    async def send_text(self, texto):
        self.msgs.append(json.loads(texto))  # também prova que tudo é JSON válido (sem NaN)

    def tipos(self):
        return {m["tipo"] for m in self.msgs}

    def ultimo(self, tipo):
        return next(m for m in reversed(self.msgs) if m["tipo"] == tipo)


def test_csv_com_cabecalho_antigo_e_preservado(monkeypatch, tmp_path):
    caminho = tmp_path / "sinais.csv"
    caminho.write_text("data_sinal,data_entrada,ativo\n2026-01-01,2026-01-01,X\n", encoding="utf-8-sig")
    monkeypatch.setattr(sessmod, "CSV_SINAIS", str(caminho))
    sessmod.gravar_csv(dict.fromkeys(sessmod.COLUNAS_CSV, "v"))
    antigos = list(tmp_path.glob("sinais_antigo_*.csv"))
    assert len(antigos) == 1 and "X" in antigos[0].read_text(encoding="utf-8-sig")
    assert caminho.read_text(encoding="utf-8-sig").splitlines()[0] == ",".join(sessmod.COLUNAS_CSV)


def test_sessao_ao_vivo_completa(monkeypatch, tmp_path):
    monkeypatch.setattr(sessmod, "N_HISTORICO", 300)
    monkeypatch.setattr(sessmod, "ATIVOS_SCANNER", ["frxEURUSD", "frxGBPUSD", "frxFECHADO"])
    monkeypatch.setattr(sessmod, "CSV_SINAIS", str(tmp_path / "sinais.csv"))
    monkeypatch.setattr(hubmod, "ESPERA_LIBERAR", 0.1)

    async def cenario():
        async with FakeDeriv(fechados={"frxFECHADO"}) as fake:
            h = hubmod.DerivHub(fake.url, intervalo=0)
            h.iniciar()
            nav = NavFalso()
            s = sessmod.Sessao(nav, h)
            try:
                await s.iniciar("frxEURUSD", "M1", 1, 0.85)
                await _esperar(
                    lambda: {"historico", "ranking", "analise", "decisao", "estado", "top3", "conexao"} <= nav.tipos(),
                    timeout=20,
                )
                assert fake.conexoes == 1, "tudo numa conexão só"
                assert fake.contar(ticks_history="frxEURUSD", subscribe=1) == 1, "série reaproveitada pelo scanner"
                hist = nav.ultimo("historico")
                assert hist["timeframe"] == "M1" and len(hist["velas"]) > 100
                r = nav.ultimo("ranking")
                assert len(r["linhas"]) == 11 and r["janela"] <= 300
                assert nav.ultimo("decisao")["estado"] in ("SEM_SINAL", "AGUARDANDO", "PREPARANDO")
                await _esperar(lambda: nav.ultimo("top3")["carregando"] == 0, timeout=20)
                top = nav.ultimo("top3")
                fechado = next(x for x in top["todos"] if x["simbolo"] == "frxFECHADO")
                assert not fechado["elegivel"] and all(x["simbolo"] != "frxFECHADO" for x in top["itens"])
                assert top["regra"] and nav.ultimo("estado")["principal"]["estado"]
                assert all(x["spark"] and x["porque"] for x in top["itens"])
                # cada mini gráfico usa as velas do PRÓPRIO ativo (eram iguais por causa do Deriv falso)
                for x in top["todos"]:
                    if x["spark"]:
                        serie = next(sv for (sim, _), sv in h.series.items() if sim == x["simbolo"])
                        fechadas, _ = s._velas(serie)
                        closes = [float(v) for v in fechadas["close"].tail(len(x["spark"]) + 5)]
                        n = len(x["spark"])  # trecho contínuo (uma vela pode ter fechado depois da mensagem)
                        assert any(closes[i : i + n] == x["spark"] for i in range(len(closes) - n + 1))
                sparks = [tuple(x["spark"]) for x in top["todos"] if x["spark"]]
                assert len(sparks) >= 2 and len(set(sparks)) == len(sparks), "mini gráficos idênticos"
                # veredito em linguagem simples, em toda mensagem de estado e de decisão
                ver = nav.ultimo("estado")["veredito"]
                assert ver["estado"] in ("ENTRAR", "PREPARANDO", "AGUARDAR", "CONFLITO") and ver["frase"]
                assert nav.ultimo("decisao")["veredito"]["estado"]
                assert nav.ultimo("analise")["humano"]["frase"]
                assert all(l["selo"]["texto"] for l in nav.ultimo("ranking")["linhas"])
                # modo observação só muda o que a tela mostra
                s.observacao = True
                n = len(nav.msgs)
                await _esperar(lambda: any(m["tipo"] == "estado" for m in nav.msgs[n:]), timeout=5)
                ver = nav.ultimo("estado")["veredito"]
                if nav.ultimo("ranking")["melhor"] is None:
                    assert ver["estado"] == "OBSERVACAO" and ver["som"] is None
            finally:
                await s.parar()
            assert all(x.refs == 0 for x in h.series.values())
            await _esperar(lambda: not h.series, timeout=5)  # assinaturas canceladas
            await h.fechar()

    rodar(cenario(), timeout=60)
