"""Camada de dados: download de velas (síncrono, para o menu e a validação) e CSV."""
import asyncio
import os

import pandas as pd

from .config import PASTA_DADOS
from .deriv import DerivClient, DerivErro
from .timeframes import COLUNAS, agregar, granularidade_base, nome_timeframe, parse_timeframe


def listar_ativos() -> list[dict]:
    async def _run():
        async with DerivClient() as c:
            return await c.ativos()
    return asyncio.run(_run())


def para_dataframe(velas: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(velas, columns=COLUNAS)
    return df.astype({"epoch": "int64", "open": float, "high": float, "low": float, "close": float})


def _progresso_console(feito: int, total: int) -> None:
    print(f"  {feito}/{total} velas baixadas...", end="\r", flush=True)


def baixar_velas(simbolo: str, timeframe: str, quantidade: int, progresso=_progresso_console) -> pd.DataFrame:
    """Baixa `quantidade` velas FECHADAS. Timeframes não nativos são montados com timeframes.agregar
    (mesma função usada no modo ao vivo)."""
    segundos = parse_timeframe(timeframe)
    base = granularidade_base(segundos)
    fator = segundos // base
    precisa = quantidade * fator + 2 * fator if fator > 1 else quantidade
    if fator > 1:
        print(f"Timeframe {nome_timeframe(segundos)} não é nativo: baixando {precisa} velas "
              f"{nome_timeframe(base)} e agregando (fator {fator}).")

    async def _run():
        async with DerivClient() as c:
            velas = await c.velas(simbolo, base, precisa, progresso)
            return velas, c.agora()

    velas, agora = asyncio.run(_run())
    if progresso:
        print()
    df = para_dataframe(velas)
    if df.empty:
        raise DerivErro(f"Nenhuma vela retornada para {simbolo}.")
    if fator > 1:
        df, _ = agregar(df, segundos, base, agora)
    df = df.tail(quantidade).reset_index(drop=True)
    df.insert(0, "datetime", pd.to_datetime(df["epoch"], unit="s", utc=True).dt.strftime("%Y-%m-%d %H:%M:%S"))
    return df


def caminho_csv(simbolo: str, timeframe: str, sufixo: str = "") -> str:
    nome = f"{simbolo}_{nome_timeframe(parse_timeframe(timeframe))}{('_' + sufixo) if sufixo else ''}.csv"
    return os.path.join(PASTA_DADOS, nome)


def salvar_csv(df: pd.DataFrame, simbolo: str, timeframe: str, sufixo: str = "") -> str:
    caminho = caminho_csv(simbolo, timeframe, sufixo)
    df.to_csv(caminho, index=False)
    return caminho


def listar_csvs() -> list[str]:
    return sorted(f for f in os.listdir(PASTA_DADOS) if f.lower().endswith(".csv"))


def granularidade_inferida(df: pd.DataFrame) -> int | None:
    """Espaçamento mais comum entre velas (em segundos)."""
    d = df["epoch"].diff()
    d = d[d > 0]
    return int(d.mode().iloc[0]) if len(d) else None


def carregar_csv(nome_ou_caminho: str) -> pd.DataFrame:
    caminho = nome_ou_caminho if os.path.isabs(nome_ou_caminho) else os.path.join(PASTA_DADOS, nome_ou_caminho)
    df = pd.read_csv(caminho)
    faltam = set(COLUNAS) - set(df.columns)
    if faltam:
        raise ValueError(f"CSV precisa das colunas {COLUNAS} (faltam: {sorted(faltam)})")
    for c in COLUNAS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    antes = len(df)
    df = df.dropna(subset=COLUNAS)
    df["epoch"] = df["epoch"].astype("int64")
    df = df.sort_values("epoch").drop_duplicates("epoch", keep="last").reset_index(drop=True)
    gran = granularidade_inferida(df)
    if gran:
        df = df[df["epoch"] % gran == 0].reset_index(drop=True)  # velas desalinhadas = artefato
    if len(df) < antes:
        print(f"Aviso: {antes - len(df)} linha(s) inválida(s), duplicada(s) ou desalinhada(s) "
              f"removida(s) de {os.path.basename(caminho)}.")
    if "datetime" not in df.columns:
        df.insert(0, "datetime", pd.to_datetime(df["epoch"], unit="s", utc=True).dt.strftime("%Y-%m-%d %H:%M:%S"))
    return df
