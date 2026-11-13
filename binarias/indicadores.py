"""Indicadores técnicos (todos causais: o valor na vela i só usa velas <= i)."""

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
