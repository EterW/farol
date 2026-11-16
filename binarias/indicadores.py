"""Indicadores técnicos (todos causais: o valor na vela i só usa velas <= i). Testados por truncamento do futuro."""

import numpy as np
import pandas as pd


def cor(df: pd.DataFrame) -> pd.Series:
    """1 = verde, -1 = vermelha, 0 = doji."""
    return np.sign(df["close"] - df["open"]).astype(int)


def sma(serie: pd.Series, periodo: int) -> pd.Series:
    """Média móvel simples."""
    return serie.rolling(int(periodo)).mean()


def _wilder(serie: pd.Series, periodo: int) -> pd.Series:
    return serie.ewm(alpha=1 / int(periodo), adjust=False).mean()


def rsi(close: pd.Series, periodo: int) -> pd.Series:
    """RSI de Wilder. Sem perdas no período -> 100; sem ganhos nem perdas -> 50."""
    delta = close.diff()
    ganho = _wilder(delta.clip(lower=0), periodo)
    perda = _wilder(-delta.clip(upper=0), periodo)
    valor = 100 - 100 / (1 + ganho / perda.replace(0, np.nan))
    valor = valor.where(~((perda == 0) & (ganho > 0)), 100.0)
    valor = valor.where(~((perda == 0) & (ganho == 0)), 50.0)
    return valor


def true_range(df: pd.DataFrame) -> pd.Series:
    """True range (amplitude real, considerando o fechamento anterior)."""
    fech_ant = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - fech_ant).abs(), (df["low"] - fech_ant).abs()], axis=1).max(
        axis=1
    )


def atr(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    """ATR de Wilder: mede o que é "perto"/"longe" em cada ativo."""
    return _wilder(true_range(df), periodo)


def adx(df: pd.DataFrame, periodo: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ADX de Wilder. Devolve (adx, +DI, -DI)."""
    alta = df["high"].diff()
    baixa = -df["low"].diff()
    dm_mais = pd.Series(np.where((alta > baixa) & (alta > 0), alta, 0.0), index=df.index)
    dm_menos = pd.Series(np.where((baixa > alta) & (baixa > 0), baixa, 0.0), index=df.index)
    atr_ = atr(df, periodo).replace(0, np.nan)
    di_mais = 100 * _wilder(dm_mais, periodo) / atr_
    di_menos = 100 * _wilder(dm_menos, periodo) / atr_
    soma = (di_mais + di_menos).replace(0, np.nan)
    dx = 100 * (di_mais - di_menos).abs() / soma
    return _wilder(dx.fillna(0), periodo), di_mais, di_menos


def bandas(close: pd.Series, periodo: int, desvios: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger: (superior, inferior, desvio-padrão)."""
    media = close.rolling(int(periodo)).mean()
    dp = close.rolling(int(periodo)).std(ddof=0)
    return media + desvios * dp, media - desvios * dp, dp


def niveis_anteriores(df: pd.DataFrame, n: int) -> tuple[pd.Series, pd.Series]:
    """Máxima e mínima das N velas ANTERIORES (sem incluir a vela atual)."""
    n = int(n)
    return df["high"].shift(1).rolling(n).max(), df["low"].shift(1).rolling(n).min()


# --------------------------------------------------------------------------- indicadores adicionais
def ema(serie: pd.Series, periodo: int) -> pd.Series:
    """Média móvel exponencial (alpha = 2 / (periodo + 1)), recursiva a partir do primeiro valor.
    Os primeiros `periodo - 1` valores ficam NaN (aquecimento), para não usar médias imaturas."""
    periodo = int(periodo)
    valor = serie.ewm(span=periodo, adjust=False).mean()
    valor.iloc[: periodo - 1] = np.nan
    return valor


def macd(close: pd.Series, rapida: int = 12, lenta: int = 26, sinal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD: (linha = EMA rápida − EMA lenta, linha de sinal = EMA da linha, histograma = linha − sinal)."""
    rapida, lenta, sinal = int(rapida), int(lenta), int(sinal)
    linha = close.ewm(span=rapida, adjust=False).mean() - close.ewm(span=lenta, adjust=False).mean()
    linha.iloc[: lenta - 1] = np.nan
    sinal_ = linha.ewm(span=sinal, adjust=False, ignore_na=True).mean()
    sinal_.iloc[: lenta + sinal - 2] = np.nan
    return linha, sinal_, linha - sinal_


def estocastico(df: pd.DataFrame, k: int = 14, d: int = 3, suavizacao: int = 3) -> tuple[pd.Series, pd.Series]:
    """Estocástico (%K, %D). %K bruto = 100 × (fechamento − mínima de k) ÷ (máxima de k − mínima de k);
    `suavizacao` > 1 = estocástico "lento" (média de %K). %D = média de %K em `d` velas.
    Faixa parada (máxima = mínima) -> 50."""
    k, d, suavizacao = int(k), int(d), int(suavizacao)
    minima = df["low"].rolling(k).min()
    maxima = df["high"].rolling(k).max()
    faixa = maxima - minima
    bruto = (100 * (df["close"] - minima) / faixa.replace(0, np.nan)).where(faixa != 0, 50.0)
    bruto = bruto.where(faixa.notna())
    pct_k = bruto.rolling(suavizacao).mean() if suavizacao > 1 else bruto
    return pct_k, pct_k.rolling(d).mean()


def williams_r(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    """Williams %R (−100 a 0) = −100 × (máxima de N − fechamento) ÷ (máxima de N − mínima de N)."""
    periodo = int(periodo)
    maxima = df["high"].rolling(periodo).max()
    minima = df["low"].rolling(periodo).min()
    faixa = maxima - minima
    valor = (-100 * (maxima - df["close"]) / faixa.replace(0, np.nan)).where(faixa != 0, -50.0)
    return valor.where(faixa.notna())


def cci(df: pd.DataFrame, periodo: int = 20, constante: float = 0.015) -> pd.Series:
    """CCI de Lambert = (preço típico − média) ÷ (constante × desvio médio absoluto), em N velas."""
    periodo = int(periodo)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    media = tp.rolling(periodo).mean()
    valores = tp.to_numpy(dtype=float)
    desvio = np.full(len(tp), np.nan)
    if len(tp) >= periodo:
        janelas = np.lib.stride_tricks.sliding_window_view(valores, periodo)
        desvio[periodo - 1 :] = np.abs(janelas - janelas.mean(axis=1, keepdims=True)).mean(axis=1)
    desvio_s = pd.Series(desvio, index=tp.index)
    valor = (tp - media) / (constante * desvio_s.replace(0, np.nan))
    return valor.where(desvio_s != 0, 0.0).where(desvio_s.notna())


def keltner(
    df: pd.DataFrame, periodo: int = 20, mult: float = 2.0, periodo_atr: int = 10
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Canais de Keltner: (superior, central, inferior) = EMA ± mult × ATR."""
    centro = ema(df["close"], periodo)
    faixa = float(mult) * atr(df, periodo_atr)
    return centro + faixa, centro, centro - faixa


def donchian(df: pd.DataFrame, n: int = 20, incluir_atual: bool = True) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Canal de Donchian: (máxima, meio, mínima) das últimas N velas (com ou sem a vela atual)."""
    n = int(n)
    alta, baixa = (df["high"], df["low"]) if incluir_atual else (df["high"].shift(1), df["low"].shift(1))
    sup, inf = alta.rolling(n).max(), baixa.rolling(n).min()
    return sup, (sup + inf) / 2, inf


def vwap(df: pd.DataFrame, janela: int = 50) -> pd.Series | None:
    """VWAP aproximado em janela móvel (preço típico ponderado pelo volume).
    Só existe com volume real: sem coluna `volume` (caso da Deriv) ou com volume todo zero -> None.
    Nenhuma estratégia do Farol usa VWAP enquanto a fonte de dados não fornecer volume."""
    if "volume" not in df or not (df["volume"].fillna(0) > 0).any():
        return None
    janela = int(janela)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].astype(float)
    soma_vol = vol.rolling(janela).sum()
    return (tp * vol).rolling(janela).sum() / soma_vol.replace(0, np.nan)


def supertrend(df: pd.DataFrame, periodo: int = 10, mult: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """SuperTrend: (linha, direção) com direção 1 = alta, −1 = baixa. Bandas = (máx+mín)/2 ± mult × ATR,
    que só se afastam quando o preço passa por elas. Aquecimento: as primeiras `periodo` velas ficam NaN."""
    periodo, mult = int(periodo), float(mult)
    n = len(df)
    linha = np.full(n, np.nan)
    direcao = np.full(n, np.nan)
    if n <= periodo:
        return pd.Series(linha, index=df.index), pd.Series(direcao, index=df.index)
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy(dtype=float)
    a = atr(df, periodo).to_numpy(dtype=float)
    fech = df["close"].to_numpy(dtype=float)
    sup_b, inf_b = hl2 + mult * a, hl2 - mult * a
    sup_f, inf_f = sup_b[periodo], inf_b[periodo]
    d = 1
    linha[periodo], direcao[periodo] = inf_f, d
    for i in range(periodo + 1, n):
        sup_f = sup_b[i] if (sup_b[i] < sup_f or fech[i - 1] > sup_f) else sup_f
        inf_f = inf_b[i] if (inf_b[i] > inf_f or fech[i - 1] < inf_f) else inf_f
        if d == 1 and fech[i] < inf_f:
            d = -1
        elif d == -1 and fech[i] > sup_f:
            d = 1
        linha[i] = inf_f if d == 1 else sup_f
        direcao[i] = d
    return pd.Series(linha, index=df.index), pd.Series(direcao, index=df.index)
