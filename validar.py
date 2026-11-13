"""Validação antes de confiar.

Baixa velas (padrão: 20000 M5 de EURUSD, GBPUSD, USDJPY, AUDUSD), roda todas as estratégias em
todos os pares, faz walk-forward (escolhe parâmetros nos 70% iniciais e testa nos 30% finais) e
gera o relatório em resultados/.

Uso:
    python validar.py
    python validar.py --usar-cache                  # reaproveita os CSVs já baixados
    python validar.py --payout 80 --expiracao 2 --empate perde
    python validar.py --ativos frxEURUSD,frxGBPUSD --velas 5000
"""

import argparse
import os
import sys
import time

import websockets

from binarias import backtest as bt
from binarias import dados
from binarias import validacao as val
from binarias.config import (
    EMPATE_PADRAO,
    FRACAO_TREINO,
    MIN_OPERACOES,
    PASTA_RESULTADOS,
    VALIDACAO_ATIVOS,
    VALIDACAO_TIMEFRAME,
    VALIDACAO_VELAS,
)
from binarias.deriv import DerivErro
from binarias.log import configurar_log, obter

log = obter("validar")


def obter_dados(ativos, tf, velas, usar_cache):
    """Baixa (ou lê do cache) as velas de cada ativo."""
    dfs, falhas = {}, {}
    for sim in ativos:
        caminho = dados.caminho_csv(sim, tf, sufixo=str(velas))
        try:
            if usar_cache and os.path.exists(caminho):
                df = dados.carregar_csv(caminho)
                if len(df) >= 0.98 * velas:
                    print(f"{sim}: {len(df)} velas do cache ({os.path.basename(caminho)})")
                    dfs[sim] = df
                    continue
            print(f"{sim}: baixando {velas} velas {tf}...")
            df = dados.baixar_velas(sim, tf, velas)
            dados.salvar_csv(df, sim, tf, sufixo=str(velas))
            if len(df) < velas:
                print(f"  Aviso: a Deriv só tinha {len(df)} velas.")
            print(f"  {df['datetime'].iat[0]} -> {df['datetime'].iat[-1]} (UTC)")
            dfs[sim] = df
        except (DerivErro, OSError, ValueError, websockets.WebSocketException) as e:
            log.error("Falha ao obter dados de %s: %s", sim, e)
            falhas[sim] = str(e)
    return dfs, falhas


def main():
    """Validação completa e relatório em resultados/."""
    ap = argparse.ArgumentParser(description="Validação walk-forward das estratégias")
    ap.add_argument("--ativos", default=",".join(VALIDACAO_ATIVOS))
    ap.add_argument("--timeframe", default=VALIDACAO_TIMEFRAME)
    ap.add_argument("--velas", type=int, default=VALIDACAO_VELAS)
    ap.add_argument("--payout", type=float, default=85.0, help="em %% (ex.: 85)")
    ap.add_argument("--expiracao", type=int, default=1)
    ap.add_argument("--treino", type=float, default=FRACAO_TREINO, help="fração de treino (0.7 = 70%%)")
    ap.add_argument("--min-ops", type=int, default=MIN_OPERACOES)
    ap.add_argument("--empate", choices=["devolve", "perde"], default=EMPATE_PADRAO)
    ap.add_argument("--usar-cache", action="store_true", help="reaproveita CSVs já baixados em data/")
    a = ap.parse_args()
    configurar_log()

    ativos = [s.strip() for s in a.ativos.split(",") if s.strip()]
    cfg = bt.ConfigBacktest(expiracao=a.expiracao, payout=a.payout / 100, empate=a.empate)
    t0 = time.time()
    dfs, falhas = obter_dados(ativos, a.timeframe, a.velas, a.usar_cache)
    if not dfs:
        print("Nenhum dado obtido. Veja resultados/erros.log.")
        return 1

    print("\nComparativo (parâmetros padrão, dados completos)...")
    comp = val.comparativo(dfs, cfg, a.min_ops)
    c_comp = os.path.join(PASTA_RESULTADOS, "validacao_comparativo.csv")
    comp.to_csv(c_comp, index=False)

    print(f"Walk-forward (escolha nos primeiros {a.treino:.0%}, teste nos {1 - a.treino:.0%} finais)...")
    wf = val.walk_forward_todos(
        dfs, cfg, a.treino, a.min_ops, progresso=lambda at, est: print(f"  {at:<10} {est:<30}", end="\r", flush=True)
    )
    print(" " * 60)
    c_wf = os.path.join(PASTA_RESULTADOS, "validacao_walkforward.csv")
    wf.to_csv(c_wf, index=False)

    info = f"Dados: {', '.join(f'{k} ({len(v)} velas {a.timeframe})' for k, v in dfs.items())}." + (
        f" FALHARAM: {', '.join(f'{k} ({v})' for k, v in falhas.items())}." if falhas else ""
    )
    resumo, texto = val.relatorio(wf, cfg, a.min_ops, info)
    if falhas:
        texto += "\n\nATENÇÃO: alguns pares não foram baixados, então 'passa em todos' considera só os pares acima."
    c_rel = os.path.join(PASTA_RESULTADOS, "validacao_relatorio.csv")
    c_txt = os.path.join(PASTA_RESULTADOS, "validacao_relatorio.txt")
    resumo.to_csv(c_rel, index=False)
    with open(c_txt, "w", encoding="utf-8") as f:
        f.write(texto + "\n")

    # tabela lado a lado (treino x teste) no terminal
    cols = [
        "ativo",
        "estrategia",
        "params_escolhidos",
        "treino_decididas",
        "treino_acerto_%",
        "treino_ic95_inf_%",
        "teste_decididas",
        "teste_acerto_%",
        "teste_ic95_inf_%",
        "teste_lucro",
        "teste_vantagem",
    ]
    import pandas as pd

    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 40):
        print(wf[[c for c in cols if c in wf]].to_string(index=False))
    print("\n" + texto)
    print(f"\nArquivos:\n  {c_comp}\n  {c_wf}\n  {c_rel}\n  {c_txt}")
    print(f"Tempo total: {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
