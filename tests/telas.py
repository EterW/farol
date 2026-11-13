"""Screenshots da interface em todos os estados (dados SIMULADOS de /api/demo).

Uso (com o servidor rodando: python live.py --porta 8765 --sem-navegador):
    python tests/telas.py                 # salva em resultados/telas/
    python tests/telas.py --url http://127.0.0.1:8000

Usa o Playwright com o Microsoft Edge já instalado no Windows (channel="msedge"); se não houver,
tenta o Chromium do Playwright (python -m playwright install chromium).
Não roda no pytest (precisa de navegador e servidor); é uma ferramenta de revisão visual.
"""
import argparse
import os
import sys

from playwright.sync_api import sync_playwright

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENARIOS = ["entrar", "preparando", "aguardar", "conflito", "observacao"]
TAMANHOS = {"desktop": (1440, 900), "celular": (390, 844)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--pasta", default=os.path.join(RAIZ, "resultados", "telas"))
    ap.add_argument("--so", default="", help="só estes cenários (separados por vírgula)")
    args = ap.parse_args()
    os.makedirs(args.pasta, exist_ok=True)
    cenarios = [c for c in CENARIOS if not args.so or c in args.so.split(",")]
    erros = []
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch(channel="msedge")
        except Exception:
            nav = p.chromium.launch()
        for nome, (w, h) in TAMANHOS.items():
            ctx = nav.new_context(viewport={"width": w, "height": h}, device_scale_factor=1 if w > 800 else 2,
                                  reduced_motion="reduce")
            ctx.add_init_script("localStorage.setItem('tourVisto','true')")
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and erros.append(f"[{nome}] {m.text}"))
            pg.on("pageerror", lambda e: erros.append(f"[{nome}] {e}"))
            for modo in ("simples", "detalhado"):
                for c in cenarios:
                    if modo == "detalhado" and c not in ("entrar", "observacao"):
                        continue
                    pg.goto(f"{args.url}/?demo={c}&modo={modo}&tour=0", wait_until="networkidle")
                    pg.wait_for_timeout(900)
                    largura = pg.evaluate("document.documentElement.scrollWidth")
                    if largura > w:
                        erros.append(f"[{nome}] {c}/{modo}: rolagem horizontal ({largura}px > {w}px)")
                    arq = os.path.join(args.pasta, f"{c}_{modo}_{nome}.png")
                    pg.screenshot(path=arq, full_page=True)
                    pg.screenshot(path=arq.replace(".png", "_dobra.png"))   # o que se vê sem rolar
                    print("ok", arq)
            ctx.close()
            # tour de primeira visita (contexto limpo, sem "tourVisto") e diálogo de alertas
            ctx = nav.new_context(viewport={"width": w, "height": h}, device_scale_factor=1 if w > 800 else 2,
                                  reduced_motion="reduce")
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: erros.append(f"[{nome}] {e}"))
            pg.goto(f"{args.url}/?demo=entrar", wait_until="networkidle")
            for passo in range(1, 5):
                pg.wait_for_timeout(1300)
                pg.screenshot(path=os.path.join(args.pasta, f"tour{passo}_{nome}.png"))
                pg.click("#tourProximo")
            pg.wait_for_timeout(300)
            pg.click("#btnAlertas")
            pg.wait_for_timeout(400)
            pg.screenshot(path=os.path.join(args.pasta, f"alertas_{nome}.png"))
            ctx.close()
        nav.close()
    if erros:
        print("\nPROBLEMAS:")
        for e in erros:
            print(" -", e)
        sys.exit(1)
    print("\nSem erros de console nem rolagem horizontal.")


if __name__ == "__main__":
    main()
