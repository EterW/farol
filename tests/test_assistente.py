"""Assistente Farol com a API SIMULADA: explica, não prevê; respostas fora das regras são descartadas."""

from types import SimpleNamespace

import pytest

from binarias import assistente as A


class ClienteFalso:
    """Imita o cliente da Anthropic: devolve um texto fixo ou levanta um erro."""

    def __init__(self, texto="", erro=None, stop="end_turn"):
        self.texto, self.erro, self.stop = texto, erro, stop
        self.chamadas = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.chamadas.append(params)
        if self.erro:
            raise self.erro
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=self.texto)])


def _cfg(chave="sk-teste", **kw):
    return A.Configuracao(provedor="anthropic", chave=chave, **kw)


def _dados(comprovada=False):
    ver = {
        "estado": "ENTRAR" if comprovada else "AGUARDAR",
        "titulo": "ENTRAR AGORA" if comprovada else "AGUARDAR",
        "frase": "Nenhuma estratégia comprovada." if not comprovada else "Entre em COMPRA ▲ na abertura desta vela.",
        "comprovada": comprovada,
        "nome": "MACD cruzamento" if comprovada else None,
        "prob": {"ok": True, "acerto": 0.6123, "inf": 0.5612, "sup": 0.6611, "n": 312} if comprovada else None,
    }
    humano = {"tendencia": "SUBINDO", "forca": "Média", "movimento": "Normal", "frase": "O preço está subindo."}
    ranking = {"break_even": 0.5405, "payout": 0.85, "min_ops": 100, "janela": 1500, "testes": 20, "correcao": "Holm"}
    return A.montar_dados("EUR/USD", "M5", ver, humano, ranking)


CHAVE = ("frxEURUSD", "M5", 1_700_000_000)
BOM = "O Farol está sem vantagem comprovada agora em EUR/USD M5. O preço está subindo, com movimento normal."


def test_resposta_valida_passa_e_recebe_aviso():
    cli = ClienteFalso(BOM)
    r = A.Assistente(_cfg(), cli).explicar(_dados(), CHAVE)
    assert r["fonte"] == "ia" and r["texto"] == BOM and r["aviso"] == A.AVISO_FINAL
    assert "informativa" in r["aviso"]
    enviado = cli.chamadas[0]["messages"][0]["content"]
    assert "EUR/USD" in enviado and "sk-teste" not in enviado, "a chave nunca vai no conteúdo"
    assert cli.chamadas[0]["model"] == "claude-opus-5-5"


def test_numero_inventado_e_rejeitado():
    texto = "O Farol está sem vantagem comprovada. A chance de acerto é de 88%."
    r = A.Assistente(_cfg(), ClienteFalso(texto)).explicar(_dados(), CHAVE)
    assert r["fonte"] == "descartada" and "88" not in r["texto"]
    assert "sem vantagem comprovada" in r["texto"]


def test_numeros_do_json_sao_aceitos_arredondados():
    texto = "A líder MACD cruzamento acerta cerca de 61,2% (entre 56,1% e 66,1%) em 312 operações; break-even 54,05%."
    ok, motivo = A.validar(texto, _dados(comprovada=True))
    assert ok, motivo
    ok, _ = A.validar("Acerto estimado de 61%, faixa de 56% a 66%.", _dados(comprovada=True))
    assert ok


@pytest.mark.parametrize(
    "texto",
    [
        "O Farol está sem vantagem comprovada, mas o preço vai subir.",
        "Sem vantagem comprovada. Recomendo esperar a próxima vela para comprar.",
        "Sem vantagem comprovada, mas é uma boa hora para entrar.",
        "Sem vantagem comprovada. Entre agora em COMPRA.",
        "Sem vantagem comprovada, porém o lucro é garantido.",
        "Sem vantagem comprovada. Pode entrar sem medo.",
    ],
)
def test_recomendacao_ou_previsao_e_rejeitada(texto):
    r = A.Assistente(_cfg(), ClienteFalso(texto)).explicar(_dados(), CHAVE)
    assert r["fonte"] == "descartada", texto


def test_estrategia_ou_ativo_fora_do_json_e_rejeitado():
    ok, motivo = A.validar("Sem vantagem comprovada; a SuperTrend + recuo parece boa.", _dados())
    assert not ok and "estratégia" in motivo
    ok, motivo = A.validar("Sem vantagem comprovada em EUR/USD, nem em GBP/JPY.", _dados())
    assert not ok and "ativo" in motivo


def test_sem_vantagem_precisa_ser_dito():
    r = A.Assistente(_cfg(), ClienteFalso("O preço está subindo com movimento normal.")).explicar(_dados(), CHAVE)
    assert r["fonte"] == "descartada"


def test_sem_chave_nao_quebra_e_nao_chama():
    cli = ClienteFalso(BOM)
    ass = A.Assistente(_cfg(chave=None), cli)
    r = ass.explicar(_dados(), CHAVE)
    assert r["fonte"] == "desativado" and not cli.chamadas
    assert "ANTHROPIC_API_KEY" in r["motivo"]
    st = ass.status()
    assert st["ativo"] is False and "sk-" not in str(st)


def test_padrao_e_desligado():
    cfg = A.Configuracao()
    assert cfg.provedor == "desligado" and not cfg.ativo
    r = A.Assistente(cfg, ClienteFalso(BOM)).explicar(_dados(), CHAVE)
    assert r["fonte"] == "desativado" and "Ative o assistente nas configurações" in r["motivo"]
    assert A.Configuracao(provedor="outra-coisa").provedor == "desligado"


def test_falha_de_rede_nao_trava():
    ass = A.Assistente(_cfg(), ClienteFalso(erro=ConnectionError("sem internet")))
    r = ass.explicar(_dados(), CHAVE)
    assert r["fonte"] == "erro" and "sem vantagem comprovada" in r["texto"]
    ass = A.Assistente(_cfg(), ClienteFalso(erro=TimeoutError()))
    assert ass.explicar(_dados(), CHAVE)["fonte"] == "erro"


def test_recusa_da_api_vira_texto_padrao():
    r = A.Assistente(_cfg(), ClienteFalso(BOM, stop="refusal")).explicar(_dados(), CHAVE)
    assert r["fonte"] == "erro"


@pytest.mark.parametrize(
    "pergunta", ["Devo entrar agora?", "vai subir?", "Compro ou vendo?", "me dá uma dica de entrada"]
)
def test_pergunta_fora_do_tema_recusada_sem_chamar(pergunta):
    cli = ClienteFalso(BOM)
    r = A.Assistente(_cfg(), cli).explicar(_dados(), CHAVE, pergunta)
    assert r["fonte"] == "recusa" and not cli.chamadas
    assert A.RECUSA in r["texto"] and "sem vantagem comprovada" in r["texto"]


def test_ia_marca_fora_do_tema():
    r = A.Assistente(_cfg(), ClienteFalso(A.FORA_DO_TEMA)).explicar(_dados(), CHAVE, "Qual o melhor time de futebol?")
    assert r["fonte"] == "recusa"


def test_pergunta_sobre_termo_pode_usar_numeros_de_referencia():
    texto = "ADX mede a força da tendência; o Farol chama de forte acima de 25. Agora: sem vantagem comprovada."
    r = A.Assistente(_cfg(), ClienteFalso(texto)).explicar(_dados(), CHAVE, "O que significa ADX?")
    assert r["fonte"] == "ia"


def test_cache_por_vela_e_limite_por_hora():
    cli = ClienteFalso(BOM)
    ass = A.Assistente(_cfg(limite_hora=2), cli)
    ass.explicar(_dados(), CHAVE)
    r = ass.explicar(_dados(), CHAVE)
    assert r.get("cache") and len(cli.chamadas) == 1, "mesma vela = cache, sem nova chamada"
    ass.explicar(_dados(), (*CHAVE[:2], CHAVE[2] + 300))
    r = ass.explicar(_dados(), (*CHAVE[:2], CHAVE[2] + 600))
    assert r["fonte"] == "limite" and len(cli.chamadas) == 2


def test_resposta_cortada_em_5_linhas():
    texto = "\n".join(["Sem vantagem comprovada."] * 9)
    r = A.Assistente(_cfg(), ClienteFalso(texto)).explicar(_dados(), CHAVE)
    assert len(r["texto"].splitlines()) == 5


def test_json_tem_so_dados_calculados():
    d = _dados(comprovada=True)
    assert d["probabilidade_estimada"]["operacoes"] == 312 and d["break_even_pct"] == 54.05
    assert d["veredito"]["estrategia_lider"] == "MACD cruzamento"
    assert "velas" not in d and "chave" not in str(d).lower()
    assert _dados()["veredito"]["estrategia_lider"] is None and "probabilidade_estimada" not in _dados()


def test_env_sem_sobrescrever(tmp_path, monkeypatch):
    arq = tmp_path / ".env"
    arq.write_text(
        "# comentário\nANTHROPIC_API_KEY=sk-do-arquivo\nFAROL_ASSISTENTE_MODELO='claude-haiku-5-5'\n", "utf-8"
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("FAROL_ASSISTENTE_MODELO", "do-ambiente")
    lidos = A.carregar_env(str(arq))
    import os

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-do-arquivo" and os.environ["FAROL_ASSISTENTE_MODELO"] == "do-ambiente"
    assert lidos["FAROL_ASSISTENTE_MODELO"] == "claude-haiku-5-5"


def test_aviso_de_ia_so_quando_a_ia_respondeu():
    r = A.Assistente(_cfg(chave=None)).explicar(_dados(), CHAVE)
    assert r["aviso"] == A.AVISO_SEM_IA and "IA" in r["aviso"] and "informativo" in r["aviso"]
