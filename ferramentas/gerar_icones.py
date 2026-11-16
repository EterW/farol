"""Gera static/icones/<id>.svg: um ícone de traço simples (24×24, cor herdada) para cada estratégia.

Uso: python ferramentas/gerar_icones.py   (o teste tests/test_estrategias.py confere que todos existem)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binarias.config import PASTA_STATIC

# Só o desenho interno; o cabeçalho é comum. Linhas = preço/indicador, retângulos = velas.
DESENHOS = {
    "seguir_cor": '<rect x="5" y="8" width="5" height="9" rx="1"/><rect x="14" y="6" width="5" height="9" rx="1"/><path d="M10 12h4"/>',
    "reversao_sequencia": '<rect x="3" y="12" width="4" height="7" rx="1"/><rect x="9" y="9" width="4" height="7" rx="1"/><path d="M15 6c4 0 6 3 4 8"/><path d="M17 13l2 2 2-2"/>',
    "cruzamento_medias": '<path d="M3 17c5 0 8-10 18-10"/><path d="M3 8c6 0 10 8 18 8"/><circle cx="12" cy="12" r="1.6"/>',
    "rsi_reversao": '<path d="M3 6h18M3 18h18" stroke-dasharray="2 2"/><path d="M3 12l4 7 4-4 4 3 6-12"/>',
    "mhi": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M8 5v14M13 5v14M18 5v14"/>',
    "tendencia_recuo": '<path d="M3 19L21 7" stroke-dasharray="2 2"/><path d="M3 16l6-5 3 3 9-9"/>',
    "bollinger_rsi": '<path d="M3 8c6-4 12 4 18 0M3 16c6-4 12 4 18 0"/><circle cx="18" cy="19" r="1.6"/>',
    "pin_bar": '<path d="M12 3v18"/><rect x="9.5" y="3" width="5" height="5" rx="1"/>',
    "rompimento_sr": '<path d="M3 9h12" stroke-dasharray="2 2"/><path d="M4 16l5-4 3 2 4-9 4 3"/>',
    "rejeicao_sr": '<path d="M3 6h18" stroke-dasharray="2 2"/><path d="M3 18l6-6 3 3 3-9 3 8 3-2"/>',
    "engolfo": '<rect x="5" y="9" width="4" height="6" rx="1"/><rect x="12" y="5" width="7" height="14" rx="1"/>',
    "macd_cruzamento": '<path d="M3 15c4 0 6-8 10-8s5 4 8 4"/><path d="M3 11c5 0 7 4 11 4s4-3 7-3"/><path d="M5 21v-2M9 21v-3M13 21v-1M17 21v-3"/>',
    "macd_tendencia": '<path d="M3 13L21 5" stroke-dasharray="2 2"/><path d="M3 17c5 0 6-6 10-6s5 2 8 2"/><path d="M6 21v-2M11 21v-3M16 21v-2"/>',
    "estocastico_reversao": '<path d="M3 5h18M3 19h18" stroke-dasharray="2 2"/><path d="M3 9l5 9 4-3 3 3 6-11"/><path d="M3 12l5 7 4-2 3 1 6-9"/>',
    "supertrend_recuo": '<path d="M3 20h4v-4h4v-3h4v-4h6"/><path d="M4 15l5-5 2 3 4-6 5-3"/>',
    "keltner_reversao": '<path d="M3 6c6 2 12-2 18 0M3 16c6 2 12-2 18 0"/><path d="M5 11l4 8 4-6"/>',
    "keltner_rompimento": '<path d="M3 8c6 2 12-2 18 0M3 16c6 2 12-2 18 0"/><path d="M5 13l5-2 4 1 6-9"/>',
    "donchian_compressao": '<path d="M3 4h7l3 6h8M3 20h7l3-6h8"/><path d="M5 12h6l4-7 4 0"/>',
    "cci_reversao": '<path d="M3 12h18" stroke-dasharray="1 2"/><path d="M3 12c3 0 3 8 6 8s3-12 6-12 3 4 6 4"/>',
    "williams_tendencia": '<path d="M3 17L21 7" stroke-dasharray="2 2"/><path d="M3 9l4 6 3-4 4 6 3-5 4 3"/>',
}

CABECALHO = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" '
    'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
)


def main() -> None:
    """Escreve um SVG por estratégia em static/icones/."""
    pasta = os.path.join(PASTA_STATIC, "icones")
    os.makedirs(pasta, exist_ok=True)
    for ident, desenho in DESENHOS.items():
        with open(os.path.join(pasta, f"{ident}.svg"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"{CABECALHO}{desenho}</svg>\n")
    print(f"{len(DESENHOS)} ícones em {pasta}")


if __name__ == "__main__":
    main()
