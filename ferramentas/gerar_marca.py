"""Gera a marca do Farol em static/marca/ (SVG, PNG e ICO). Rode de novo se mudar cores ou traços.

    python ferramentas/gerar_marca.py --fonte caminho/BricolageGrotesque.ttf

O símbolo é desenhado aqui (geometria própria: torre afunilada, lanterna e feixe de luz). O nome
"Farol" é convertido em contornos com a fonte dos títulos (Bricolage Grotesque, licença OFL), assim
o SVG não depende da fonte estar instalada. Os PNG são renderizados pelo navegador (Playwright).
Ferramenta de desenvolvimento: precisa de `fonttools` e `playwright` (não são usadas pelo app).
"""

import argparse
import base64
import os
import struct

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, "static", "marca")

# Paletas (coerentes com static/tema.css)
ESCURO = {
    "torre_a": "#c4b3ff",
    "torre_b": "#8d6bff",
    "faixa": "#09090f",
    "luz": "#f6f2ff",
    "feixe": "#c9b8ff",
    "feixe_op": 0.9,
    "base": "#a990ff",
    "texto": "#efedf8",
    "fundo": "#09090f",
}
CLARO = {
    "torre_a": "#7a5cf5",
    "torre_b": "#4b2fc4",
    "faixa": "#ffffff",
    "luz": "#ede7ff",
    "luz_borda": "#6b4ff0",
    "feixe": "#7a5cf5",
    "feixe_op": 0.55,
    "base": "#6b4ff0",
    "texto": "#17132e",
    "fundo": "#ffffff",
}


def simbolo(p: dict, pref: str) -> str:
    """Corpo do símbolo (viewBox 0 0 64 64). `pref` evita ids repetidos quando há vários na página."""
    return f"""
  <defs>
    <linearGradient id="{pref}t" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{p["torre_a"]}"/><stop offset="1" stop-color="{p["torre_b"]}"/>
    </linearGradient>
    <linearGradient id="{pref}fd" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{p["feixe"]}" stop-opacity="{p["feixe_op"]}"/>
      <stop offset="1" stop-color="{p["feixe"]}" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="{pref}fe" x1="1" y1="0" x2="0" y2="0">
      <stop offset="0" stop-color="{p["feixe"]}" stop-opacity="{p["feixe_op"] * 0.45:.2f}"/>
      <stop offset="1" stop-color="{p["feixe"]}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <path d="M36 15.6 62 6v22.4l-26-7.8z" fill="url(#{pref}fd)"/>
  <path d="M28 15.6 9 9.4v13.8l19-3.6z" fill="url(#{pref}fe)"/>
  <path d="M26.6 14.2 32 9l5.4 5.2z" fill="url(#{pref}t)"/>
  <rect x="28" y="14.2" width="8" height="7.6" rx="1.6" fill="{p["luz"]}"{_borda(p)}/>
  <rect x="25.6" y="21.8" width="12.8" height="2.6" rx="1.3" fill="url(#{pref}t)"/>
  <path d="M28.2 25.6h7.6l3.5 27.4H24.7z" fill="url(#{pref}t)"/>
  <path d="M27.05 34.6h9.9l.55 4.3H26.5z" fill="{p["faixa"]}" opacity=".55"/>
  <path d="M25.95 43.3h12.1l.5 4H25.45z" fill="{p["faixa"]}" opacity=".55"/>
  <path d="M17 56.4h30" stroke="{p["base"]}" stroke-width="2.6" stroke-linecap="round" opacity=".6"/>"""


def _borda(p: dict) -> str:
    return f' stroke="{p["luz_borda"]}" stroke-width="1.1"' if p.get("luz_borda") else ""


def simbolo_compacto(p: dict, pref: str) -> str:
    """Versão robusta para 16–48 px (favicon e ícones): torre mais larga, feixe maior, sem detalhes finos."""
    return f"""
  <defs>
    <linearGradient id="{pref}t" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{p["torre_a"]}"/><stop offset="1" stop-color="{p["torre_b"]}"/>
    </linearGradient>
    <linearGradient id="{pref}fd" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{p["feixe"]}" stop-opacity="{p["feixe_op"]}"/>
      <stop offset="1" stop-color="{p["feixe"]}" stop-opacity=".08"/>
    </linearGradient>
    <radialGradient id="{pref}g" cx="32" cy="19.5" r="22" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{p["feixe"]}" stop-opacity=".28"/><stop offset="1" stop-color="{p["feixe"]}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <circle cx="32" cy="19.5" r="22" fill="url(#{pref}g)"/>
  <path d="M38 16.5 61 8v23l-23-8z" fill="url(#{pref}fd)"/>
  <path d="M24.5 15 32 8.5l7.5 6.5z" fill="url(#{pref}t)"/>
  <rect x="26" y="15" width="12" height="9" rx="2.2" fill="{p["luz"]}"{_borda(p)}/>
  <rect x="22.5" y="24" width="19" height="3.6" rx="1.8" fill="url(#{pref}t)"/>
  <path d="M26 29.4h12l4.8 27.2H21.2z" fill="url(#{pref}t)"/>
  <path d="M24.25 39.4h15.5l.9 5.2H23.35z" fill="{p["faixa"]}" opacity=".55"/>"""


def svg_simbolo(p: dict, pref: str = "s", fundo: bool = False, raio: int = 14, compacto: bool = False) -> str:
    tile = f'<rect width="64" height="64" rx="{raio}" fill="{p["fundo"]}"/>' if fundo else ""
    corpo = simbolo_compacto(p, pref) if compacto else simbolo(p, pref)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Farol">'
        f"<title>Farol</title>{tile}{corpo}\n</svg>\n"
    )


def contorno_texto(fonte: TTFont, texto: str, tamanho: float, x0: float, base: float, rastreio: float = -0.012):
    """Caminho SVG do texto (contornos) e a largura ocupada, em unidades do viewBox."""
    upm = fonte["head"].unitsPerEm
    esc = tamanho / upm
    cmap, glifos, hmtx = fonte.getBestCmap(), fonte.getGlyphSet(), fonte["hmtx"]
    partes, x = [], x0
    ajustes = {("F", "a"): -0.055}  # par F-a precisa de aproximação (kerning manual, conferido no render)
    anterior = None
    for ch in texto:
        nome = cmap[ord(ch)]
        x += ajustes.get((anterior, ch), 0) * tamanho
        pen = SVGPathPen(glifos)
        glifos[nome].draw(TransformPen(pen, (esc, 0, 0, -esc, x, base)))
        partes.append(pen.getCommands())
        x += hmtx[nome][0] * esc + rastreio * tamanho
        anterior = ch
    return " ".join(partes), x - x0 - rastreio * tamanho


def svg_logo(p: dict, fonte: TTFont, pref: str) -> str:
    caminho, largura = contorno_texto(fonte, "Farol", 46, 74, 50)
    total = round(74 + largura + 2)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} 64" role="img" aria-label="Farol">'
        f"<title>Farol</title>{simbolo(p, pref)}\n"
        f'  <path d="{caminho}" fill="{p["texto"]}"/>\n</svg>\n'
    )


def ico(pngs: dict[int, bytes]) -> bytes:
    """Arquivo .ico com PNGs embutidos (aceito por todos os navegadores atuais)."""
    cab = struct.pack("<HHH", 0, 1, len(pngs))
    entradas, dados, desloc = b"", b"", 6 + 16 * len(pngs)
    for lado, png in sorted(pngs.items()):
        entradas += struct.pack("<BBBBHHII", lado % 256, lado % 256, 0, 0, 1, 32, len(png), desloc + len(dados))
        dados += png
    return cab + entradas + dados


def renderizar(svgs: dict[str, tuple[str, int, int]]) -> dict[str, bytes]:
    """{nome: (svg, largura, altura)} -> PNG (fundo transparente), pelo navegador."""
    from playwright.sync_api import sync_playwright

    saida = {}
    with sync_playwright() as pw:
        try:
            nav = pw.chromium.launch(channel="msedge")
        except Exception:  # noqa: BLE001 - sem Edge, usa o Chromium do Playwright
            nav = pw.chromium.launch()
        pg = nav.new_page()
        for nome, (svg, w, h) in svgs.items():
            uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
            pg.set_viewport_size({"width": w, "height": h})
            pg.set_content(
                f'<html><body style="margin:0;background:transparent">'
                f'<img src="{uri}" style="display:block;width:{w}px;height:{h}px"></body></html>'
            )
            pg.wait_for_timeout(50)
            saida[nome] = pg.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": w, "height": h})
        nav.close()
    return saida


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fonte", required=True, help="BricolageGrotesque[opsz,wdth,wght].ttf (Google Fonts, OFL)")
    args = ap.parse_args()
    fonte = instantiateVariableFont(TTFont(args.fonte), {"wght": 800, "opsz": 96, "wdth": 100})
    os.makedirs(DESTINO, exist_ok=True)
    arquivos = {
        "simbolo.svg": svg_simbolo(ESCURO, "se"),
        "simbolo-fundo-claro.svg": svg_simbolo(CLARO, "sc"),
        "logo.svg": svg_logo(ESCURO, fonte, "le"),
        "logo-fundo-claro.svg": svg_logo(CLARO, fonte, "lc"),
        "favicon.svg": svg_simbolo(ESCURO, "fv", fundo=True, compacto=True),
        "simbolo-compacto.svg": svg_simbolo(ESCURO, "sk", compacto=True),
    }
    for nome, conteudo in arquivos.items():
        with open(os.path.join(DESTINO, nome), "w", encoding="utf-8") as f:
            f.write(conteudo)
    tile = svg_simbolo(ESCURO, "ic", fundo=True, raio=0, compacto=True)  # o sistema arredonda o ícone
    largura_logo = int(arquivos["logo.svg"].split('viewBox="0 0 ')[1].split(" ")[0])
    pngs = renderizar(
        {
            "icone-192.png": (tile, 192, 192),
            "icone-512.png": (tile, 512, 512),
            "f16": (arquivos["favicon.svg"], 16, 16),
            "f32": (arquivos["favicon.svg"], 32, 32),
            "f48": (arquivos["favicon.svg"], 48, 48),
            "logo.png": (arquivos["logo.svg"], largura_logo * 6, 64 * 6),
            "logo-fundo-claro.png": (arquivos["logo-fundo-claro.svg"], largura_logo * 6, 64 * 6),
        }
    )
    for nome in ("icone-192.png", "icone-512.png", "logo.png", "logo-fundo-claro.png"):
        with open(os.path.join(DESTINO, nome), "wb") as f:
            f.write(pngs[nome])
    with open(os.path.join(DESTINO, "favicon.ico"), "wb") as f:
        f.write(ico({16: pngs["f16"], 32: pngs["f32"], 48: pngs["f48"]}))
    print("Marca gerada em", DESTINO)
    for n in sorted(os.listdir(DESTINO)):
        print(f"  {n:<26}{os.path.getsize(os.path.join(DESTINO, n)):>8} bytes")


if __name__ == "__main__":
    main()
