"""Filtro OPCIONAL de qualidade do momento — DESLIGADO por padrão e NUNCA aplicado automaticamente.

Para cada sinal ao vivo o Farol só REGISTRA o que o filtro teria feito (colunas filtro_* do CSV). Se o
filtro ajuda ou não, quem decide são os dados (relatório /resultados e, depois, walk-forward no
laboratório). Ligar um filtro escolhido olhando os mesmos dados seria escolher a vencedora depois.

Critérios (todos medidos só com velas FECHADAS até o sinal):
  * liquidez:     a vela de entrada começa na sobreposição Londres/Nova York (12h–16h UTC);
  * volatilidade: ATR(14) da vela do sinal no percentil >= 20 das últimas 500 velas (evita mercado parado,
                  que gera empates e ruído);
  * variação:     o corpo |fechamento − abertura| da vela do sinal >= 10% do ATR (vela "de verdade").
"""

from datetime import datetime, timezone

import pandas as pd

from .config import FILTRO_ATR_PERCENTIL_MIN, FILTRO_HORAS_LIQUIDEZ_UTC, FILTRO_VARIACAO_MIN_ATR, JANELA_VOL
from .indicadores import atr

EXPLICACAO = (
    "Filtro de qualidade (desligado, só registrado): liquidez = entrada entre "
    f"{FILTRO_HORAS_LIQUIDEZ_UTC[0]}h e {FILTRO_HORAS_LIQUIDEZ_UTC[1]}h UTC (Londres + Nova York); volatilidade = "
    f"ATR no percentil ≥ {FILTRO_ATR_PERCENTIL_MIN}; variação = corpo da vela do sinal ≥ "
    f"{FILTRO_VARIACAO_MIN_ATR:.0%} do ATR. Nada é aplicado automaticamente."
)


def _sn(v: bool | None) -> str:
    return "" if v is None else ("sim" if v else "não")


def avaliar(df: pd.DataFrame, epoch_entrada: int) -> dict:
    """Colunas filtro_* para um sinal na última vela de `df` (velas fechadas) com entrada em `epoch_entrada`."""
    hora = datetime.fromtimestamp(int(epoch_entrada), tz=timezone.utc).hour
    ini, fim = FILTRO_HORAS_LIQUIDEZ_UTC
    liquidez: bool | None = ini <= hora < fim
    vol: bool | None = None
    var: bool | None = None
    if len(df) >= 30:
        a = atr(df, 14)
        ult = a.tail(JANELA_VOL).dropna()
        atual = float(a.iat[-1]) if pd.notna(a.iat[-1]) else None
        if atual and len(ult):
            vol = float((ult <= atual).mean() * 100) >= FILTRO_ATR_PERCENTIL_MIN
            corpo = abs(float(df["close"].iat[-1]) - float(df["open"].iat[-1]))
            var = corpo >= FILTRO_VARIACAO_MIN_ATR * atual
    passaria = None if vol is None or var is None else bool(liquidez and vol and var)
    return {
        "filtro_liquidez": _sn(liquidez),
        "filtro_volatilidade": _sn(vol),
        "filtro_variacao": _sn(var),
        "filtro_passaria": _sn(passaria),
    }
