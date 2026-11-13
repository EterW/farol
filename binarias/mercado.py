"""Análise de mercado com critérios explícitos: tendência, força (ADX), volatilidade (ATR) e vela atual."""
import pandas as pd

from .indicadores import adx, atr, sma

PERIODO_MA = 50
VELAS_INCLINACAO = 10
LIMIAR_INCLINACAO = 0.5    # em ATRs ao longo de VELAS_INCLINACAO velas
PERIODO_ADX = 14
PERIODO_ATR = 14
JANELA_VOL = 500
ADX_MODERADO, ADX_FORTE = 20, 25
VOL_SAUDAVEL = (20, 90)    # percentil do ATR considerado "saudável" (nem parado, nem caótico)

CRITERIO = (
    f"Tendência: ALTA se o preço fecha acima da média de {PERIODO_MA} e a média subiu mais de "
    f"{LIMIAR_INCLINACAO} ATR nas últimas {VELAS_INCLINACAO} velas; BAIXA no inverso; senão LATERAL. "
    f"Força pelo ADX({PERIODO_ADX}): < {ADX_MODERADO} fraca, {ADX_MODERADO}–{ADX_FORTE} moderada, "
    f"≥ {ADX_FORTE} forte. Volatilidade: percentil do ATR({PERIODO_ATR}) atual nas últimas {JANELA_VOL} velas "
    f"(saudável entre {VOL_SAUDAVEL[0]} e {VOL_SAUDAVEL[1]})."
)


def _num(v: float, casas: int = 2) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def classificar_volatilidade(percentil: float) -> str:
    if percentil < 10:
        return "muito baixa"
    if percentil < 20:
        return "baixa"
    if percentil <= 80:
        return "normal"
    if percentil <= 90:
        return "alta"
    return "muito alta"


def forca_adx(valor: float) -> str:
    return "forte" if valor >= ADX_FORTE else "moderada" if valor >= ADX_MODERADO else "fraca"


TENDENCIA_HUMANA = {"ALTA": "SUBINDO", "BAIXA": "DESCENDO", "LATERAL": "LATERAL"}
FORCA_HUMANA = {"fraca": "Fraca", "moderada": "Média", "forte": "Forte"}
VELA_HUMANA = {"ALTA": "subindo", "BAIXA": "descendo", "DOJI": "parada"}


def movimento_humano(volatilidade: str) -> str:
    """Volatilidade (percentil do ATR) em palavras simples."""
    if volatilidade in ("muito baixa", "baixa"):
        return "Calmo"
    if volatilidade in ("alta", "muito alta"):
        return "Agitado"
    return "Normal"


def humano(a: dict) -> dict:
    """Tradução da análise técnica para quem não conhece os termos (sem números técnicos)."""
    if not a.get("ok"):
        return {"ok": False, "frase": f"Ainda não dá para analisar este mercado ({a.get('motivo', 'sem dados')})."}
    tend = TENDENCIA_HUMANA[a["tendencia"]]
    forca = FORCA_HUMANA[a["forca"]]
    mov = movimento_humano(a["volatilidade"])
    vela = VELA_HUMANA[a["vela_atual"]["direcao"]]
    if tend == "LATERAL":
        base = "O preço está andando de lado, sem direção clara"
    else:
        intensidade = {"Fraca": "devagar", "Média": "com alguma firmeza", "Forte": "com firmeza"}[forca]
        base = f"O preço está {'subindo' if tend == 'SUBINDO' else 'descendo'} {intensidade}"
    mov_txt = {"Calmo": "o mercado está calmo, com pouco movimento",
               "Normal": "o movimento está normal",
               "Agitado": "o mercado está agitado, com oscilações grandes"}[mov]
    frase = f"{base}, e {mov_txt}."
    return {"ok": True, "tendencia": tend, "forca": forca, "movimento": mov, "vela": vela, "frase": frase,
            "lateral": tend == "LATERAL"}


def analisar(df: pd.DataFrame, formando: pd.DataFrame | None = None, nome: str = "") -> dict:
    """`df`: velas FECHADAS. `formando`: vela em formação (0/1 linha), só para a direção da vela atual."""
    minimo = PERIODO_MA + VELAS_INCLINACAO + 2
    if len(df) < minimo:
        return {"ok": False, "motivo": f"poucas velas ({len(df)}/{minimo})", "criterio": CRITERIO}
    ma = sma(df["close"], PERIODO_MA)
    atr_s = atr(df, PERIODO_ATR)
    adx_s, di_mais, di_menos = adx(df, PERIODO_ADX)
    preco = float(df["close"].iat[-1])
    atr_v = float(atr_s.iat[-1])
    ma_v = float(ma.iat[-1])
    if not atr_v or pd.isna(atr_v) or pd.isna(ma_v):
        return {"ok": False, "motivo": "ATR zero (mercado parado)", "criterio": CRITERIO}
    inclinacao = (ma_v - float(ma.iat[-1 - VELAS_INCLINACAO])) / atr_v
    distancia = (preco - ma_v) / atr_v
    if preco > ma_v and inclinacao > LIMIAR_INCLINACAO:
        tendencia = "ALTA"
    elif preco < ma_v and inclinacao < -LIMIAR_INCLINACAO:
        tendencia = "BAIXA"
    else:
        tendencia = "LATERAL"
    adx_v = float(adx_s.iat[-1])
    forca = forca_adx(adx_v)
    ult_atr = atr_s.tail(JANELA_VOL).dropna()
    percentil = float((ult_atr <= atr_v).mean() * 100)
    vol = classificar_volatilidade(percentil)

    if formando is not None and len(formando):
        vela, fonte = formando.iloc[-1], "em formação"
    else:
        vela, fonte = df.iloc[-1], "última fechada"
    corpo = float(vela["close"] - vela["open"])
    direcao_vela = "ALTA" if corpo > 0 else "BAIXA" if corpo < 0 else "DOJI"

    prefixo = f"{nome}: " if nome else ""
    if tendencia == "LATERAL":
        txt_tend = f"mercado LATERAL (média de {PERIODO_MA} com inclinação de {_num(inclinacao)} ATR)"
    else:
        txt_tend = (f"tendência de {tendencia} {forca} (ADX {_num(adx_v, 0)}), preço {_num(abs(distancia))} ATR "
                    f"{'acima' if distancia > 0 else 'abaixo'} da média de {PERIODO_MA}")
    if tendencia == "LATERAL" and adx_v >= ADX_FORTE:
        txt_tend += f", mas ADX {_num(adx_v, 0)} indica movimento forte recente"
    vela_txt = {"ALTA": "verde (subindo)", "BAIXA": "vermelha (caindo)", "DOJI": "sem corpo (indecisão)"}[direcao_vela]
    resumo = (f"{prefixo}{txt_tend[0].upper() + txt_tend[1:]}. Volatilidade {vol} "
              f"(ATR no percentil {_num(percentil, 0)} das últimas {len(ult_atr)} velas). "
              f"Vela {fonte}: {vela_txt}, corpo de {_num(abs(corpo) / atr_v)} ATR.")
    saida = {
        "ok": True,
        "tendencia": tendencia,
        "forca": forca,
        "adx": round(adx_v, 1),
        "di_mais": round(float(di_mais.iat[-1]), 1),
        "di_menos": round(float(di_menos.iat[-1]), 1),
        "preco": preco,
        "ma": ma_v,
        "distancia_ma_atr": round(distancia, 2),
        "inclinacao_atr": round(inclinacao, 2),
        "atr": atr_v,
        "atr_pct_preco": round(100 * atr_v / preco, 4) if preco else None,
        "atr_percentil": round(percentil, 1),
        "volatilidade": vol,
        "vol_saudavel": VOL_SAUDAVEL[0] <= percentil <= VOL_SAUDAVEL[1],
        "vela_atual": {"direcao": direcao_vela, "corpo_atr": round(abs(corpo) / atr_v, 2), "fonte": fonte},
        "criterio": CRITERIO,
        "resumo": resumo,
    }
    saida["humano"] = humano(saida)
    return saida
