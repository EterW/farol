"""Screenshots da interface em todos os estados (dados SIMULADOS de /api/demo) + checagens visuais.

Uso (com o servidor rodando: python live.py --porta 8765 --sem-navegador):
    python tests/telas.py                 # salva em resultados/telas/
    python tests/telas.py --so entrar,conflito --tamanhos 1440

Checa automaticamente: erros de console, rolagem horizontal, texto visível menor que 12px, veredito
visível ao abrir (página no topo) e barra compacta do veredito ao rolar.
Usa o Playwright com o Microsoft Edge do Windows (channel="msedge"); sem ele, o Chromium do Playwright.
Não roda no pytest (precisa de navegador e servidor); é uma ferramenta de revisão visual.
"""

import argparse
import os
import sys

from playwright.sync_api import sync_playwright

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENARIOS = ["entrar", "preparando", "aguardar", "conflito", "observacao"]
TAMANHOS = {"1440": (1440, 900), "1920": (1920, 1080), "390": (390, 844)}
MENOR_FONTE = 12  # px: legendas; texto de leitura usa 13px ou mais

JS_FONTES = """(minimo) => {
  const ruins = [];
  for (const e of document.querySelectorAll('body *')) {
    const temTexto = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!temTexto) continue;
    const r = e.getBoundingClientRect(), st = getComputedStyle(e);
    if (!r.width || !r.height || st.visibility === 'hidden' || e.closest('[hidden], .tv-lightweight-charts')) continue;
    const px = parseFloat(st.fontSize);
    if (px < minimo) ruins.push(`${e.tagName.toLowerCase()}.${e.className}: ${px}px "${e.textContent.trim().slice(0, 30)}"`);
  }
  return ruins.slice(0, 8);
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--pasta", default=os.path.join(RAIZ, "resultados", "telas"))
    ap.add_argument("--so", default="", help="só estes cenários (separados por vírgula)")
    ap.add_argument("--tamanhos", default=",".join(TAMANHOS), help="ex.: 1440,390")
    args = ap.parse_args()
    os.makedirs(args.pasta, exist_ok=True)
    cenarios = [c for c in CENARIOS if not args.so or c in args.so.split(",")]
    problemas = []
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch(channel="msedge")
        except Exception:
            nav = p.chromium.launch()
        for nome in args.tamanhos.split(","):
            w, h = TAMANHOS[nome]
            celular = w < 800
            ctx = nav.new_context(
                viewport={"width": w, "height": h}, device_scale_factor=2 if celular else 1, reduced_motion="reduce"
            )
            ctx.add_init_script("localStorage.setItem('tourVisto','true')")
            pg = ctx.new_page()
            pg.on("console", lambda m, n=nome: m.type == "error" and problemas.append(f"[{n}] console: {m.text}"))
            pg.on("pageerror", lambda e, n=nome: problemas.append(f"[{n}] erro: {e}"))
            for modo in ("simples", "detalhado"):
                for c in cenarios:
                    pg.goto(f"{args.url}/?demo={c}&modo={modo}&tour=0", wait_until="networkidle")
                    pg.wait_for_timeout(900)
                    rotulo = f"[{nome}] {c}/{modo}"
                    if pg.evaluate("document.documentElement.scrollWidth") > w:
                        problemas.append(f"{rotulo}: rolagem horizontal")
                    topo = pg.evaluate("[scrollY, document.getElementById('veredito').getBoundingClientRect().top]")
                    if topo[0] != 0 or topo[1] < 0:
                        problemas.append(f"{rotulo}: página não abriu no topo / veredito cortado ({topo})")
                    for ruim in pg.evaluate(JS_FONTES, MENOR_FONTE):
                        problemas.append(f"{rotulo}: texto pequeno {ruim}")
                    base = os.path.join(args.pasta, f"{c}_{modo}_{nome}")
                    pg.screenshot(path=base + "_dobra.png")  # o que se vê sem rolar
                    pg.screenshot(path=base + ".png", full_page=True)
            # marca no cabeçalho (logo, nome e frase de posicionamento)
            pg.goto(f"{args.url}/?demo=aguardar&tour=0", wait_until="networkidle")
            pg.locator("#topo").screenshot(path=os.path.join(args.pasta, f"marca_topo_{nome}.png"))
            # barra compacta ao rolar + "mostrar todos os sinais" + letra G
            pg.goto(f"{args.url}/?demo=preparando&modo=detalhado&tour=0", wait_until="networkidle")
            pg.wait_for_timeout(700)
            pg.mouse.wheel(0, 2400 if celular else 900)
            pg.wait_for_timeout(500)
            if pg.evaluate("document.getElementById('vBarra').hidden"):
                problemas.append(f"[{nome}] barra compacta do veredito não apareceu ao rolar")
            pg.screenshot(path=os.path.join(args.pasta, f"rolado_barra_compacta_{nome}.png"))
            pg.goto(f"{args.url}/?demo=entrar&tour=0", wait_until="networkidle")
            pg.check("#chkTodos")
            pg.wait_for_timeout(500)
            pg.locator("#cartaoGrafico").screenshot(path=os.path.join(args.pasta, f"grafico_todos_sinais_{nome}.png"))
            pg.uncheck("#chkTodos")
            pg.click(".grupo-letra button[data-letra='g']")
            pg.wait_for_timeout(400)
            if pg.evaluate("document.documentElement.scrollWidth") > w:
                problemas.append(f"[{nome}] letra G: rolagem horizontal")
            pg.screenshot(path=os.path.join(args.pasta, f"letra_grande_{nome}.png"))
            pg.click(".grupo-letra button[data-letra='m']")
            # cartões novos: assistente, "Minha banca" (simulador, diário, bloqueio do dia), Aprender, Como decide
            pg.goto(f"{args.url}/?demo=entrar&tour=0", wait_until="networkidle")
            pg.wait_for_timeout(700)
            pg.click("#btnExplicar")
            pg.wait_for_timeout(300)
            pg.locator("#cartaoAssistente").screenshot(path=os.path.join(args.pasta, f"assistente_{nome}.png"))
            pg.click("#bcSimulador summary")
            pg.click("#btnSimular")
            pg.wait_for_timeout(1200)
            pg.locator("#cartaoBanca").screenshot(path=os.path.join(args.pasta, f"banca_simulador_{nome}.png"))
            for _ in range(3):
                pg.click("#cartaoBanca [data-res=LOSS]")
                pg.wait_for_timeout(400)
            pg.click("#bcDiario summary")
            pg.wait_for_timeout(300)
            if pg.evaluate("document.getElementById('faixaBloqueio').hidden"):
                problemas.append(f"[{nome}] 3 losses seguidos e a faixa 'Limite do dia atingido' não apareceu")
            pg.locator("#cartaoBanca").screenshot(path=os.path.join(args.pasta, f"banca_bloqueada_{nome}.png"))
            pg.evaluate("scrollTo(0, 0)")
            pg.wait_for_timeout(300)
            pg.screenshot(path=os.path.join(args.pasta, f"faixa_bloqueio_{nome}.png"))
            for ruim in pg.evaluate(JS_FONTES, MENOR_FONTE):
                problemas.append(f"[{nome}] cartões novos: texto pequeno {ruim}")
            for qual in ("glossario", "silencio"):
                pg.goto(f"{args.url}/?demo=aguardar&tour=0&aprender={qual}", wait_until="networkidle")
                pg.wait_for_timeout(800)
                pg.screenshot(path=os.path.join(args.pasta, f"aprender_{qual}_{nome}.png"))
            pg.goto(f"{args.url}/como-decide", wait_until="networkidle")
            pg.wait_for_timeout(500)
            if pg.evaluate("document.documentElement.scrollWidth") > w:
                problemas.append(f"[{nome}] como-decide: rolagem horizontal")
            for ruim in pg.evaluate(JS_FONTES, MENOR_FONTE):
                problemas.append(f"[{nome}] como-decide: texto pequeno {ruim}")
            pg.screenshot(path=os.path.join(args.pasta, f"como_decide_{nome}.png"), full_page=True)
            ctx.close()
            # tour de primeira visita (contexto limpo) e diálogo de alertas
            ctx = nav.new_context(
                viewport={"width": w, "height": h}, device_scale_factor=2 if celular else 1, reduced_motion="reduce"
            )
            pg = ctx.new_page()
            pg.on("pageerror", lambda e, n=nome: problemas.append(f"[{n}] erro: {e}"))
            pg.goto(f"{args.url}/?demo=entrar", wait_until="networkidle")
            for passo in range(1, 6):
                pg.wait_for_timeout(900)
                pg.screenshot(path=os.path.join(args.pasta, f"tour{passo}_{nome}.png"))
                pg.click("#tourProximo")
            pg.wait_for_timeout(500)
            if pg.evaluate("scrollY") != 0:
                problemas.append(f"[{nome}] depois do tour a página não voltou ao topo")
            pg.click("#btnAlertas")
            pg.wait_for_timeout(400)
            pg.screenshot(path=os.path.join(args.pasta, f"alertas_{nome}.png"))
            ctx.close()
            print(f"ok {nome}")
        nav.close()
    if problemas:
        print("\nPROBLEMAS:")
        for e in problemas:
            print(" -", e)
        sys.exit(1)
    print("\nSem erros de console, sem rolagem horizontal, sem texto < 12px, veredito visível ao abrir.")


if __name__ == "__main__":
    main()
