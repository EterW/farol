"""Ponta a ponta (pytest + Playwright): troca de ativo e de tempo gráfico contra o Deriv FALSO.

Sobe o servidor do Farol numa porta livre apontando para tests/fake_deriv.py e abre a página num navegador
sem janela. Alterna M1→M2→M3→M5→M1 e três ativos, 10 rodadas (metade delas trocando rápido, sem esperar
carregar) e confere a cada parada:
  * o veredito sai do "carregando" (e não vai para erro) em até 30 s;
  * a tela mostra o ativo/tempo pedido e as velas têm o espaçamento do tempo pedido (nada do anterior);
  * mensagens atrasadas de um contexto antigo são descartadas;
  * "Operações desta sessão" filtra por ativo + tempo ("Este ativo") e rotula tudo em "Todas";
  * nenhum erro no console.
Pula sozinho se o Playwright ou um navegador não estiverem instalados.
"""

import asyncio
import socket
import threading
import time

import pytest

pw = pytest.importorskip("playwright.sync_api")

from fake_deriv import FakeDeriv  # noqa: E402

TFS = {"M1": 60, "M2": 120, "M3": 180, "M5": 300}
SEQ_TF = ["M1", "M2", "M3", "M5", "M1"]
ATIVOS = ["frxEURUSD", "frxGBPUSD", "frxUSDJPY"]
RODADAS = 10


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def farol_com_deriv_falso():
    """Deriv falso (thread com loop próprio) + servidor do Farol (uvicorn em thread)."""
    import uvicorn

    from binarias import servidor
    from binarias import sessao as sessmod

    pronto, fim = threading.Event(), None
    caixa: dict = {}

    def rodar_fake():
        nonlocal fim
        loop = asyncio.new_event_loop()
        fim = loop.create_future()

        async def principal():
            async with FakeDeriv() as fake:
                caixa["url"] = fake.url
                pronto.set()
                await fim

        loop.run_until_complete(principal())

    t_fake = threading.Thread(target=rodar_fake, daemon=True)
    t_fake.start()
    assert pronto.wait(10)
    antigos = (servidor.hub.url, servidor.hub.intervalo, sessmod.ATIVOS_SCANNER)
    servidor.hub.url, servidor.hub.intervalo = caixa["url"], 0.01
    sessmod.ATIVOS_SCANNER = ["frxEURUSD", "frxGBPUSD", "frxAUDUSD"]
    porta = _porta_livre()
    srv = uvicorn.Server(uvicorn.Config(servidor.app, host="127.0.0.1", port=porta, log_level="warning"))
    t_srv = threading.Thread(target=srv.run, daemon=True)
    t_srv.start()
    t0 = time.time()
    while not srv.started:
        assert time.time() - t0 < 15, "servidor não subiu"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{porta}"
    srv.should_exit = True
    t_srv.join(10)
    servidor.hub.url, servidor.hub.intervalo, sessmod.ATIVOS_SCANNER = antigos
    fim.get_loop().call_soon_threadsafe(fim.set_result, None)
    t_fake.join(10)


@pytest.fixture(scope="module")
def pagina(farol_com_deriv_falso):
    with pw.sync_playwright() as p:
        nav = None
        for canal in ("msedge", None):
            try:
                nav = p.chromium.launch(channel=canal) if canal else p.chromium.launch()
                break
            except Exception:
                continue
        if nav is None:
            pytest.skip("nenhum navegador do Playwright disponível")
        ctx = nav.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script("localStorage.setItem('tourVisto','true')")
        pg = ctx.new_page()
        erros: list[str] = []
        pg.on("console", lambda m: m.type == "error" and erros.append(m.text))
        pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(f"{farol_com_deriv_falso}/?teste=1&tour=0&modo=detalhado", wait_until="domcontentloaded")
        pg.wait_for_function("window.farol && document.getElementById('selTf').options.length > 3", timeout=15000)
        yield pg, erros
        nav.close()


def trocar(pg, simbolo: str, tf: str) -> None:
    """Escolhe ativo + tempo no diálogo e clica em Conectar (como a pessoa faria) e espera o novo sid."""
    antes = pg.evaluate("window.farol.estado().sid")
    pg.evaluate(
        """([sim, tf]) => {
            const d = document.getElementById('dlgAtivo'), s = document.getElementById('selAtivo');
            if (![...s.options].some(o => o.value === sim)) s.add(new Option(sim, sim));
            s.value = sim; document.getElementById('selTf').value = tf;
            if (!d.open) d.showModal();
            document.getElementById('btnDlgConectar').click();
        }""",
        [simbolo, tf],
    )
    pg.wait_for_function("antes => window.farol.estado().sid !== antes", arg=antes, timeout=5000)


def esperar_pronto(pg, simbolo: str, tf: str) -> dict:
    pg.wait_for_function(
        """([sim, tf]) => {
            const e = window.farol.estado(), v = document.getElementById('veredito').dataset.estado;
            return e.simbolo === sim && e.tf === tf && document.body.dataset.contexto === sim + '|' + tf
                   && v && !['CARREGANDO', 'INICIO', 'ERRO'].includes(v);
        }""",
        arg=[simbolo, tf],
        timeout=30000,
    )
    return conferir(pg, simbolo, tf)


def conferir(pg, simbolo: str, tf: str) -> dict:
    e = pg.evaluate("window.farol.estado()")
    assert (e["simbolo"], e["tf"], e["seg"]) == (simbolo, tf, TFS[tf])
    assert pg.evaluate("document.getElementById('veredito').dataset.estado") not in ("CARREGANDO", "ERRO")
    barras = e["barras"]
    assert len(barras) > 50, "gráfico sem velas"
    difs = {b - a for a, b in zip(barras, barras[1:])}
    assert all(d > 0 and d % TFS[tf] == 0 for d in difs), f"velas de outro tempo gráfico misturadas: {sorted(difs)[:5]}"
    assert tf in pg.inner_text("#lgAtivo") and tf in pg.inner_text("#vContexto")
    # "Este ativo": só operações do contexto atual
    pg.click("#opsAbaAtivo")
    ctx = pg.evaluate("[...document.querySelectorAll('#listaOps li.op')].map(li => [li.dataset.simbolo, li.dataset.tf])")
    assert all(c == [simbolo, tf] for c in ctx), f"operação de outro contexto em 'Este ativo': {ctx}"
    return e


def test_trocas_de_ativo_e_tempo_nao_travam_nem_misturam(pagina):
    pg, erros = pagina
    trocar(pg, "frxEURUSD", "M1")
    esperar_pronto(pg, "frxEURUSD", "M1")
    descartadas_antes = pg.evaluate("window.farol.estado().descartadas")
    for rodada in range(RODADAS):
        rapido = rodada % 2 == 1
        alvo = None
        for k, tf in enumerate(SEQ_TF):
            alvo = (ATIVOS[(rodada + k) % len(ATIVOS)], tf)
            trocar(pg, *alvo)
            if rapido:
                pg.wait_for_timeout(60)  # troca antes do carregamento anterior terminar
            else:
                esperar_pronto(pg, *alvo)
        esperar_pronto(pg, *alvo)
        pg.wait_for_timeout(1500)  # respostas atrasadas do contexto anterior não podem sobrescrever o atual
        conferir(pg, *alvo)
    assert pg.evaluate("window.farol.estado().descartadas") > descartadas_antes, (
        "nas trocas rápidas deveria haver mensagens atrasadas descartadas"
    )
    assert not erros, f"erros no console: {erros}"


def test_operacoes_filtradas_por_ativo_e_tempo_e_resposta_atrasada_ignorada(pagina):
    pg, erros = pagina
    trocar(pg, "frxGBPUSD", "M2")
    e = esperar_pronto(pg, "frxGBPUSD", "M2")
    sid_gbp = e["sid"]
    t = e["barras"][-2] - 0  # epoch local do gráfico não importa aqui; só o rótulo
    sinal = {"tipo": "sinal", "op": 9001, "id": "engolfo", "nome": "Engolfo", "dir": "CALL", "t": t,
             "registrado": True, "principal": False, "ativo": "frxGBPUSD", "timeframe": "M2"}
    pg.evaluate("m => window.farol.tratar(m)", {**sinal, "sid": "contexto-velho"})  # atrasada: ignorar
    pg.evaluate("m => window.farol.tratar(m)", {**sinal, "sid": sid_gbp})
    ops = pg.evaluate("window.farol.estado().ops")
    assert [o["op"] for o in ops if o["op"] == 9001] == [9001], "a mensagem do contexto velho não pode entrar"
    assert "GBP/USD · M2" in pg.inner_text("#listaOps")
    # troca: a operação some de "Este ativo", aparece em "Todas" com rótulo e como cancelada
    trocar(pg, "frxEURUSD", "M5")
    esperar_pronto(pg, "frxEURUSD", "M5")
    assert "GBP/USD" not in pg.inner_text("#listaOps")
    pg.click("#opsAbaTodas")
    texto = pg.inner_text("#listaOps")
    assert "GBP/USD · M2" in texto and "cancelada" in texto
    # resultado atrasado do contexto velho não altera nada
    pg.evaluate("m => window.farol.tratar(m)", {"tipo": "resultado", "op": 9001, "resultado": "WIN", "sid": sid_gbp})
    assert next(o for o in pg.evaluate("window.farol.estado().ops") if o["op"] == 9001)["resultado"] == "CANCELADO"
    pg.click("#opsAbaAtivo")
    assert not erros, f"erros no console: {erros}"
