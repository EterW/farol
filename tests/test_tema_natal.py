"""Tema de Natal (só visual): o Automático liga nas datas certas e o aviso de risco aparece nos dois temas.

* Datas: roda a lógica REAL de static/tema-natal.js no Node (pula se o Node não estiver instalado).
* Aviso de risco / vereditos: abre a página de demonstração no navegador (Playwright) com tema Padrão e Natal
  e confere que o rodapé de risco está visível, com o mesmo texto, e que o veredito é o mesmo nos dois.
"""

import json
import os
import shutil
import socket
import subprocess
import threading
import time

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(RAIZ, "static", "tema-natal.js")

# (ano, mês, dia) -> o Automático deve estar no Natal?
DATAS = {
    (2026, 11, 30): False,
    (2026, 12, 1): True,
    (2026, 12, 15): True,
    (2026, 12, 25): True,
    (2026, 12, 31): True,
    (2027, 1, 1): True,
    (2027, 1, 6): True,
    (2027, 1, 7): False,
    (2027, 2, 1): False,
    (2027, 7, 15): False,
}


def _rodar_node(codigo: str):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node não instalado")
    r = subprocess.run([node, "-e", codigo], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(r.stdout)


def test_automatico_ativa_so_de_1_dezembro_a_6_janeiro():
    datas = [list(d) for d in DATAS]
    codigo = f"""
      const t = require({json.dumps(JS)});
      const out = {json.dumps(datas)}.map(([a, m, d]) => {{
        const dt = new Date(a, m - 1, d, 12);
        const r = (e) => t.resolverTema(e, dt);
        return [t.natalNaData(dt), r("auto"), r("padrao"), r("natal"), r("lixo")];
      }});
      console.log(JSON.stringify(out));
    """
    for (data, esperado), (natal, auto, padrao, fixo, lixo) in zip(DATAS.items(), _rodar_node(codigo), strict=True):
        assert natal is esperado, data
        assert auto == ("natal" if esperado else "padrao"), data
        assert padrao == "padrao" and fixo == "natal" and lixo == "padrao", data


# ------------------------------------------------------------------ navegador
@pytest.fixture(scope="module")
def url_farol():
    pytest.importorskip("playwright.sync_api")
    import uvicorn

    from binarias import servidor

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    # lifespan desligado: a demonstração não precisa do hub (nada de conexão real com a Deriv neste teste)
    cfg = uvicorn.Config(servidor.app, host="127.0.0.1", port=porta, log_level="warning", lifespan="off")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    t0 = time.time()
    while not srv.started:
        assert time.time() - t0 < 15, "servidor não subiu"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{porta}"
    srv.should_exit = True
    t.join(10)


def test_aviso_de_risco_e_veredito_iguais_nos_dois_temas(url_farol):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        nav = None
        for canal in ("msedge", None):
            try:
                nav = p.chromium.launch(channel=canal) if canal else p.chromium.launch()
                break
            except Exception:
                continue
        if nav is None:
            pytest.skip("nenhum navegador do Playwright disponível")
        vistos = {}
        for tema in ("padrao", "natal"):
            ctx = nav.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script("localStorage.setItem('tourVisto','true')")
            pg = ctx.new_page()
            erros: list[str] = []
            pg.on("pageerror", lambda e, erros=erros: erros.append(str(e)))
            pg.goto(f"{url_farol}/?demo=entrar&tour=0&tema={tema}", wait_until="networkidle")
            pg.wait_for_timeout(600)
            assert pg.evaluate("document.documentElement.dataset.tema") == tema
            aviso = pg.locator(".rodape-risco")
            assert aviso.is_visible()
            caixa = aviso.bounding_box()
            assert caixa and caixa["y"] + caixa["height"] <= 900 + 1, "aviso de risco fora da tela"
            # nada da decoração por cima do aviso nem do veredito
            for sel in (".rodape-risco", "#veredito"):
                topo = pg.evaluate(
                    """s => { const r = document.querySelector(s).getBoundingClientRect();
                              const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                              return !!e.closest(s); }""",
                    sel,
                )
                assert topo, f"algo cobre {sel} no tema {tema}"
            vistos[tema] = (aviso.inner_text(), pg.inner_text("#vTitulo"), pg.inner_text("#vFrase"))
            assert not erros, erros
            ctx.close()
        nav.close()
    texto = vistos["natal"][0]
    assert "Nenhum sinal é garantia" in texto and "perda total" in texto
    assert vistos["padrao"] == vistos["natal"], "o tema mudou texto de veredito ou do aviso de risco"
