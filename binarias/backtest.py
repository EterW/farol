"""Motor de backtest para opções binárias (CALL/PUT com expiração em velas)."""

import os
from dataclasses import asdict, dataclass

import pandas as pd

from .config import EMPATE_PADRAO, EXPIRACAO_PADRAO, PASTA_RESULTADOS, PAYOUT_PADRAO
from .estatistica import break_even, wilson

COLUNAS_OPS = [
    "idx_sinal",
    "idx_fim",
    "data_sinal",
    "data_entrada",
    "direcao",
    "preco_entrada",
    "preco_saida",
    "resultado",
    "gale",
    "lucro",
    "banca",
]


@dataclass
class ConfigBacktest:
    """Parâmetros de uma simulação (expiração, payout, gale, banca e regra de empate)."""

    expiracao: int = EXPIRACAO_PADRAO  # expiração em quantidade de velas
    payout: float = PAYOUT_PADRAO  # 0.85 = 85%
    valor_entrada: float = 10.0
    gales: int = 0  # nº máximo de martingales
    fator_gale: float = 2.0  # multiplicador da entrada a cada gale
    banca_inicial: float = 1000.0
    empate: str = EMPATE_PADRAO  # "devolve" ou "perde"

    def __post_init__(self):
        if self.empate not in ("devolve", "perde"):
            raise ValueError("empate deve ser 'devolve' ou 'perde'")
        if not 0 < self.payout <= 5:
            raise ValueError("payout deve ser uma fração (ex.: 0.85)")


def resolver(direcao: str, preco_entrada: float, preco_saida: float, empate: str = EMPATE_PADRAO) -> str:
    """Resultado de uma operação. Usado pelo backtest E pelo modo ao vivo (mesma regra)."""
    if preco_saida == preco_entrada:
        return "EMPATE" if empate == "devolve" else "LOSS"
    return "WIN" if (preco_saida > preco_entrada) == (direcao == "CALL") else "LOSS"


@dataclass
class ResultadoBacktest:
    """Operações simuladas e o resumo estatístico."""

    operacoes: pd.DataFrame
    resumo: dict


def executar(df: pd.DataFrame, sinais: pd.Series, cfg: ConfigBacktest) -> ResultadoBacktest:
    """Sinal na vela i -> entra na abertura da vela i+1 e expira no fechamento da vela i+expiracao.
    Em caso de loss com gale disponível, repete a mesma direção logo na vela seguinte.
    Não abre nova operação enquanto houver uma em andamento (incluindo gales); um novo sinal pode
    ser gerado no fechamento da vela de expiração (igual ao modo ao vivo).
    Operações que não terminam dentro dos dados são descartadas (nada de resultado parcial)."""
    abert = df["open"].to_numpy()
    fech = df["close"].to_numpy()
    datas = df["datetime"].to_numpy() if "datetime" in df else df["epoch"].to_numpy()
    sinais = sinais.reindex(df.index).to_numpy()
    n = len(df)
    exp = max(1, int(cfg.expiracao))

    ops = []
    banca = cfg.banca_inicial
    livre_a_partir = 0  # índice da 1ª vela em que um novo sinal pode ser avaliado

    for i in range(n):
        direcao = sinais[i]
        if i < livre_a_partir or direcao not in ("CALL", "PUT"):
            continue
        entrada = i + 1
        valor = cfg.valor_entrada
        lucro_total = 0.0
        resultado = None
        gale = 0
        completa = False
        primeira_entrada: float | None = None
        preco_out: float | None = None
        while True:
            fim = entrada + exp - 1
            if fim >= n:
                break  # dados acabaram no meio da operação
            preco_in, preco_out = abert[entrada], fech[fim]
            if primeira_entrada is None:
                primeira_entrada = preco_in
            resultado = resolver(direcao, preco_in, preco_out, cfg.empate)
            if resultado == "WIN":
                lucro_total += valor * cfg.payout
            elif resultado == "LOSS":
                lucro_total -= valor
            if resultado == "LOSS" and gale < cfg.gales:
                gale += 1
                valor *= cfg.fator_gale
                entrada = fim + 1
                continue
            completa = True
            break
        if not completa:
            break  # nenhuma operação posterior caberia nos dados
        assert primeira_entrada is not None and preco_out is not None  # operação completa
        banca += lucro_total
        ops.append(
            {
                "idx_sinal": i,
                "idx_fim": fim,
                "data_sinal": datas[i],
                "data_entrada": datas[i + 1],
                "direcao": direcao,
                "preco_entrada": float(primeira_entrada),
                "preco_saida": float(preco_out),
                "resultado": resultado,
                "gale": gale,
                "lucro": round(lucro_total, 2),
                "banca": round(banca, 2),
            }
        )
        livre_a_partir = fim

    operacoes = pd.DataFrame(ops, columns=COLUNAS_OPS)
    return ResultadoBacktest(operacoes, resumir(operacoes, cfg))


def _maior_sequencia(serie: pd.Series, valor: str) -> int:
    maior = atual = 0
    for v in serie:
        if v == "EMPATE":
            continue
        atual = atual + 1 if v == valor else 0
        maior = max(maior, atual)
    return maior


def resumir(ops: pd.DataFrame, cfg: ConfigBacktest) -> dict:
    """Resumo das operações: acerto, IC 95%, lucro, drawdown e sequências."""
    total = len(ops)
    wins = int((ops["resultado"] == "WIN").sum())
    losses = int((ops["resultado"] == "LOSS").sum())
    empates = int((ops["resultado"] == "EMPATE").sum())
    curva = pd.concat([pd.Series([cfg.banca_inicial]), ops["banca"]], ignore_index=True)
    drawdown = (curva.cummax() - curva).max() if total else 0.0
    inf, sup = wilson(wins, wins + losses)
    resumo = {
        "operacoes": total,
        "wins": wins,
        "losses": losses,
        "empates": empates,
        "acerto_%": round(100 * wins / (wins + losses), 2) if wins + losses else 0.0,
        "ic95_inf_%": round(100 * inf, 2) if wins + losses else None,
        "ic95_sup_%": round(100 * sup, 2) if wins + losses else None,
        "lucro": round(float(ops["lucro"].sum()), 2) if total else 0.0,
        "banca_final": round(float(curva.iloc[-1]), 2),
        "max_drawdown": round(float(drawdown), 2),
        "max_wins_seguidos": _maior_sequencia(ops["resultado"], "WIN"),
        "max_losses_seguidos": _maior_sequencia(ops["resultado"], "LOSS"),
    }
    for g in range(cfg.gales + 1):
        rotulo = "wins_sem_gale" if g == 0 else f"wins_gale_{g}"
        resumo[rotulo] = int(((ops["resultado"] == "WIN") & (ops["gale"] == g)).sum())
    if cfg.gales == 0:
        # acerto mínimo para empatar com este payout, e payout necessário para empatar com este acerto
        resumo["acerto_break_even_%"] = round(100 * break_even(cfg.payout), 2)
        if wins:
            resumo["payout_necessario_%"] = round(100 * losses / wins, 2)
    return resumo


def imprimir_resumo(nome: str, res: ResultadoBacktest, cfg: ConfigBacktest) -> None:
    """Mostra o resumo no terminal."""
    print("\n" + "=" * 52)
    print(f" {nome}")
    print("=" * 52)
    for k, v in asdict(cfg).items():
        print(f"  {k:<22}{v}")
    print("-" * 52)
    for k, v in res.resumo.items():
        print(f"  {k:<22}{v}")
    print("=" * 52)
    if cfg.gales:
        print("  Atenção: com gale, o 'acerto' conta sequências; o risco real está no drawdown.")


def salvar_operacoes(res: ResultadoBacktest, nome_arquivo: str) -> str:
    """Grava as operações em resultados/ e devolve o caminho."""
    caminho = os.path.join(PASTA_RESULTADOS, nome_arquivo)
    res.operacoes.to_csv(caminho, index=False)
    return caminho


def comparar(resultados: dict[str, ResultadoBacktest]) -> pd.DataFrame:
    """Tabela comparativa de várias estratégias, ordenada pelo lucro."""
    tabela = pd.DataFrame({nome: r.resumo for nome, r in resultados.items()}).T
    return tabela.sort_values("lucro", ascending=False)
