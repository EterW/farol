"""Timeframes: parsing e agregação de velas. Usado igualmente pelo download (backtest)
e pelo modo ao vivo, para que os dois montem as velas exatamente do mesmo jeito."""

import pandas as pd

# Granularidades (em segundos) aceitas nativamente pela Deriv em ticks_history
GRANULARIDADES_DERIV = [60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400]
UNIDADES = {"M": 60, "H": 3600, "D": 86400}
COLUNAS = ["epoch", "open", "high", "low", "close"]


def parse_timeframe(tf: str) -> int:
    """Converte 'M1', 'M20', 'H4', 'D1'... em segundos."""
    tf = str(tf).strip().upper()
    if len(tf) < 2 or tf[0] not in UNIDADES or not tf[1:].isdigit() or int(tf[1:]) <= 0:
        raise ValueError(f"Timeframe inválido: '{tf}'. Use formatos como M1, M20, H1, H4, D1.")
    return int(tf[1:]) * UNIDADES[tf[0]]


def nome_timeframe(segundos: int) -> str:
    """Converte segundos no nome canônico (3600 -> H1, 1200 -> M20)."""
    if segundos % 86400 == 0:
        return f"D{segundos // 86400}"
    if segundos % 3600 == 0:
        return f"H{segundos // 3600}"
    return f"M{segundos // 60}"


def granularidade_inferida(df: pd.DataFrame) -> int | None:
    """Espaçamento mais comum entre velas (em segundos); None se não houver ao menos 2 velas."""
    d = df["epoch"].diff()
    d = d[d > 0]
    return int(d.mode().iloc[0]) if len(d) else None


def linhas_ohlc(df: pd.DataFrame) -> list[list]:
    """Velas no formato enviado ao navegador: [epoch, open, high, low, close]."""
    return [
        [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in df[COLUNAS].itertuples(index=False)
    ]


def granularidade_base(segundos: int) -> int:
    """Maior granularidade nativa da Deriv que divide exatamente o timeframe pedido.
    Ex.: M20 -> M10, M45 -> M15, H6 -> H2, M7 -> M1."""
    candidatas = [g for g in GRANULARIDADES_DERIV if segundos % g == 0]
    if not candidatas:
        raise ValueError("O timeframe precisa ser múltiplo de 1 minuto.")
    return max(candidatas)


def vazio() -> pd.DataFrame:
    """DataFrame de velas vazio, com as colunas e tipos certos."""
    return pd.DataFrame({c: pd.Series(dtype="int64" if c == "epoch" else float) for c in COLUNAS})


def agregar(
    base: pd.DataFrame, segundos: int, gran_base: int, agora: float | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Agrupa velas da granularidade `gran_base` em velas de `segundos`, alinhadas ao epoch (UTC),
    como a Deriv faz. Devolve (fechadas, formando) — `formando` tem 0 ou 1 linha.

    Regras (as mesmas no backtest e ao vivo):
      * a primeira vela é descartada se estiver incompleta (o histórico começou no meio dela);
      * com `agora`: uma vela está fechada se início + duração <= agora;
        sem `agora` (CSV/arquivo): a última vela é considerada em formação se estiver incompleta;
      * velas internas incompletas (buracos de mercado) são mantidas.
    """
    if base.empty:
        return vazio(), vazio()
    fator = max(1, segundos // gran_base)
    d = base[COLUNAS].sort_values("epoch").drop_duplicates("epoch", keep="last")
    grupo = d["epoch"].astype("int64") - d["epoch"].astype("int64") % segundos
    agg = d.groupby(grupo, sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), n=("open", "size")
    )
    agg.index.name = "epoch"
    agg = agg.reset_index()
    if fator > 1 and len(agg) and agg["n"].iat[0] < fator:
        agg = agg.iloc[1:]
    if agora is not None:
        fechada = (agg["epoch"] + segundos) <= agora
    else:
        fechada = pd.Series(True, index=agg.index)
        if fator > 1 and len(agg) and agg["n"].iat[-1] < fator:
            fechada.iloc[-1] = False
    fechadas = agg[fechada][COLUNAS].reset_index(drop=True)
    formando = agg[~fechada][COLUNAS].tail(1).reset_index(drop=True)
    return fechadas, formando
