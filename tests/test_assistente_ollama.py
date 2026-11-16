"""Assistente com o provedor Ollama, contra um servidor Ollama SIMULADO (HTTP de verdade, numa porta livre).

As mesmas regras valem para qualquer provedor: número/estratégia fora do JSON e recomendação são rejeitados.
Ollama parado, modelo inexistente ou lento = mensagem clara com o comando, sem travar.
"""

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_assistente import BOM, CHAVE, _dados

from binarias import assistente as A


class OllamaFalso:
    """Servidor que imita POST /api/chat e GET /api/tags do Ollama."""

    def __init__(self):
        self.resposta = BOM
        self.modelos = {"llama3.2"}
        self.atraso = 0.0
        self.status_erro = None
        self.pedidos = []
        dono = self

        class Tratador(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, codigo, obj):
                corpo = json.dumps(obj).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def do_GET(self):
                self._json(200, {"models": [{"name": m} for m in dono.modelos]})

            def do_POST(self):
                corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                dono.pedidos.append((self.path, corpo))
                if dono.atraso:
                    time.sleep(dono.atraso)
                if dono.status_erro:
                    return self._json(dono.status_erro, {"error": "falha interna"})
                if corpo.get("model") not in dono.modelos:
                    return self._json(404, {"error": f'model "{corpo.get("model")}" not found, try pulling it first'})
                self._json(
                    200,
                    {"model": corpo["model"], "message": {"role": "assistant", "content": dono.resposta}, "done": True},
                )

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        self.url = f"http://127.0.0.1:{self.servidor.server_address[1]}"
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def fechar(self):
        self.servidor.shutdown()
        self.servidor.server_close()


@pytest.fixture
def ollama():
    o = OllamaFalso()
    yield o
    o.fechar()


def _ass(url, **kw):
    return A.Assistente(A.Configuracao(provedor="ollama", ollama_url=url, **kw))


def _porta_fechada():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()  # ninguém escuta nesta porta
    return f"http://127.0.0.1:{porta}"


def test_resposta_valida_passa(ollama):
    r = _ass(ollama.url).explicar(_dados(), CHAVE)
    assert r["fonte"] == "ia" and r["texto"] == BOM and r["aviso"] == A.AVISO_FINAL
    caminho, corpo = ollama.pedidos[0]
    assert caminho == "/api/chat" and corpo["model"] == "llama3.2" and corpo["stream"] is False
    assert corpo["messages"][0] == {"role": "system", "content": A.SISTEMA}, "mesmas regras no prompt do sistema"
    assert "EUR/USD" in corpo["messages"][1]["content"]


def test_numero_inventado_rejeitado(ollama):
    ollama.resposta = "O Farol está sem vantagem comprovada, mas a assertividade é de 88%."
    r = _ass(ollama.url).explicar(_dados(), CHAVE)
    assert r["fonte"] == "descartada" and "88" not in r["texto"]


def test_estrategia_fora_do_json_rejeitada(ollama):
    ollama.resposta = "Sem vantagem comprovada agora; olhe a SuperTrend + recuo."
    assert _ass(ollama.url).explicar(_dados(), CHAVE)["fonte"] == "descartada"


@pytest.mark.parametrize(
    "texto",
    [
        "Sem vantagem comprovada, mas entre agora em COMPRA.",
        "Sem vantagem comprovada; o preço vai subir.",
        "Sem vantagem comprovada. Recomendo comprar na próxima vela.",
    ],
)
def test_recomendacao_rejeitada(ollama, texto):
    ollama.resposta = texto
    assert _ass(ollama.url).explicar(_dados(), CHAVE)["fonte"] == "descartada"


def test_pensamento_do_modelo_e_removido_antes_de_validar(ollama):
    ollama.resposta = "<think>talvez 88% e vai subir</think>" + BOM
    r = _ass(ollama.url).explicar(_dados(), CHAVE)
    assert r["fonte"] == "ia" and r["texto"] == BOM


def test_pergunta_proibida_nem_chega_ao_ollama(ollama):
    r = _ass(ollama.url).explicar(_dados(), CHAVE, "devo entrar agora?")
    assert r["fonte"] == "recusa" and not ollama.pedidos


def test_ollama_parado_mostra_como_instalar():
    inicio = time.time()
    r = _ass(_porta_fechada()).explicar(_dados(), CHAVE)
    assert time.time() - inicio < 10, "não pode travar"
    assert r["fonte"] == "erro" and "sem vantagem comprovada" in r["texto"]
    assert "não está rodando" in r["motivo"] and "winget install Ollama.Ollama" in r["motivo"]
    assert "ollama pull llama3.2" in r["motivo"]


def test_modelo_inexistente_mostra_ollama_pull(ollama):
    r = _ass(ollama.url, modelo="qwen-que-nao-existe").explicar(_dados(), CHAVE)
    assert r["fonte"] == "erro" and "não está instalado" in r["motivo"]
    assert "ollama pull qwen-que-nao-existe" in r["motivo"]


def test_erro_interno_e_lentidao_nao_travam(ollama):
    ollama.status_erro = 500
    r = _ass(ollama.url).explicar(_dados(), CHAVE)
    assert r["fonte"] == "erro" and "erro 500" in r["motivo"]
    ollama.status_erro, ollama.atraso = None, 2.0
    inicio = time.time()
    r = _ass(ollama.url, tempo_limite=0.5).explicar(_dados(), (*CHAVE[:2], 99))
    assert time.time() - inicio < 2.0 and r["fonte"] == "erro" and "não respondeu" in r["motivo"]


def test_configuracao_do_env(monkeypatch, tmp_path):
    for k in list(os.environ):
        if k.startswith(("ASSISTENTE_", "FAROL_ASSISTENTE_")) or k == "ANTHROPIC_API_KEY":
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(A, "carregar_env", lambda *a: {})
    cfg = A.Configuracao.do_ambiente()
    assert cfg.provedor == "desligado" and not cfg.ativo, "padrão = desligado"
    monkeypatch.setenv("ASSISTENTE_PROVEDOR", "ollama")
    cfg = A.Configuracao.do_ambiente()
    assert cfg.ativo and cfg.local and cfg.ollama_url == "http://127.0.0.1:11434"
    assert cfg.tempo_limite == 60.0 and cfg.modelo == "llama3.2"
    monkeypatch.setenv("ASSISTENTE_MODELO", "qwen2.5:7b")
    assert A.Configuracao.do_ambiente().modelo == "qwen2.5:7b"
    st = A.Assistente(A.Configuracao.do_ambiente()).status()
    assert st["provedor"] == "ollama" and st["local"] and "não saem da sua máquina" in st["privacidade"]
    monkeypatch.setenv("ASSISTENTE_PROVEDOR", "anthropic")
    monkeypatch.delenv("ASSISTENTE_MODELO")
    cfg = A.Configuracao.do_ambiente()
    assert not cfg.ativo and "ANTHROPIC_API_KEY" in cfg.motivo_desligado
    assert cfg.modelo == "claude-opus-5-5" and cfg.tempo_limite == 20.0


def test_cache_separado_por_provedor(ollama):
    ass = _ass(ollama.url)
    ass.explicar(_dados(), CHAVE)
    ass.explicar(_dados(), CHAVE)
    assert len(ollama.pedidos) == 1
    ass.config.modelo = "outro"
    ollama.modelos.add("outro")
    ass.explicar(_dados(), CHAVE)
    assert len(ollama.pedidos) == 2, "trocar de modelo não reaproveita a explicação de outro modelo"
