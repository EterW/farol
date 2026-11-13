"""Validação antes de confiar: comparativo em vários pares + walk-forward (treino 70% / teste 30%).

Walk-forward sem olhar o final:
  * TREINO: sinais e operações calculados SÓ com df[:corte]; operações precisam terminar antes do corte.
    Para cada estratégia, cada combinação de parâmetros da grade é avaliada e a melhor é escolhida
    pelo limite inferior do IC de Wilson menos o break-even (exigindo o mínimo de operações).
  * TESTE: os parâmetros escolhidos são aplicados aos 30% finais. Os indicadores podem usar velas do
    treino como aquecimento (é passado), e só contam operações com sinal a partir do corte.
Passa = no TESTE de TODOS os pares: >= min_ops operações E limite inferior do IC acima do break-even.
"""

from dataclasses import replace

import pandas as pd

from . import backtest as bt
from .config import FRACAO_TREINO, MIN_OPERACOES
from .estatistica import break_even
from .estrategias import ESTRATEGIAS
from .log import obter
from .ranking import estatisticas

log = obter("validacao")


def avaliar_trecho(
    df: pd.DataFrame, est, params: dict, cfg: bt.ConfigBacktest, inicio: int, fim: int, min_ops: int
) -> dict:
    """Operações com sinal em [inicio, fim), vendo SÓ as velas df[:fim]."""
    parte = df.iloc[:fim]
    ops = bt.executar(parte, est.gerar_sinais(parte, **params), cfg).operacoes
    return estatisticas(ops[ops["idx_sinal"] >= inicio], cfg.payout, min_ops)


def nota_treino(st: dict, be: float, min_ops: int) -> tuple:
    """Critério de escolha no treino (maior é melhor)."""
    if st["decididas"] == 0:
        return (-1, -1.0, -1e18)
    return (1 if st["decididas"] >= min_ops else 0, st["ic_inf"] - be, st["lucro"])


def walk_forward(
    df: pd.DataFrame, est, cfg: bt.ConfigBacktest, fracao: float = FRACAO_TREINO, min_ops: int = MIN_OPERACOES
) -> dict:
    """Escolhe parâmetros no treino e mede no teste (dados nunca vistos na escolha)."""
    cfg = replace(cfg, gales=0)
    be = break_even(cfg.payout)
    corte = int(len(df) * fracao)
    melhor, melhor_nota, melhor_st = None, None, None
    combos = est.combinacoes()
    for params in combos:
        st = avaliar_trecho(df, est, params, cfg, 0, corte, min_ops)
        nota = nota_treino(st, be, min_ops)
        if melhor_nota is None or nota > melhor_nota:
            melhor, melhor_nota, melhor_st = params, nota, st
    assert melhor is not None  # há sempre ao menos a combinação padrão
    teste = avaliar_trecho(df, est, melhor, cfg, corte, len(df), min_ops)
    return {"params": melhor, "combinacoes": len(combos), "corte": corte, "treino": melhor_st, "teste": teste}


def _linha_stats(prefixo: str, st: dict) -> dict:
    def pct(v):
        return None if v is None else round(100 * v, 2)

    return {
        f"{prefixo}_ops": st["operacoes"],
        f"{prefixo}_decididas": st["decididas"],
        f"{prefixo}_acerto_%": pct(st["acerto"]),
        f"{prefixo}_ic95_inf_%": pct(st["ic_inf"]),
        f"{prefixo}_ic95_sup_%": pct(st["ic_sup"]),
        f"{prefixo}_lucro": st["lucro"],
        f"{prefixo}_vantagem": st["vantagem"],
    }


def comparativo(
    dfs: dict[str, pd.DataFrame], cfg: bt.ConfigBacktest, min_ops: int = MIN_OPERACOES, estrategias=None
) -> pd.DataFrame:
    """Todas as estratégias (parâmetros padrão) em todos os pares, dados completos."""
    cfg = replace(cfg, gales=0)
    linhas = []
    for ativo, df in dfs.items():
        for est in estrategias or ESTRATEGIAS:
            try:
                st = avaliar_trecho(df, est, {}, cfg, 0, len(df), min_ops)
            except Exception as e:
                log.exception("Comparativo: %s em %s", est.id, ativo)
                linhas.append({"ativo": ativo, "estrategia": est.nome, "erro": str(e)})
                continue
            linhas.append({"ativo": ativo, "estrategia": est.nome, "velas": len(df), **_linha_stats("total", st)})
    return pd.DataFrame(linhas)


def walk_forward_todos(
    dfs: dict[str, pd.DataFrame],
    cfg: bt.ConfigBacktest,
    fracao: float = FRACAO_TREINO,
    min_ops: int = MIN_OPERACOES,
    estrategias=None,
    progresso=None,
) -> pd.DataFrame:
    """Walk-forward de todas as estratégias em todos os pares."""
    linhas = []
    for ativo, df in dfs.items():
        for est in estrategias or ESTRATEGIAS:
            if progresso:
                progresso(ativo, est.nome)
            try:
                wf = walk_forward(df, est, cfg, fracao, min_ops)
            except Exception as e:
                log.exception("Walk-forward: %s em %s", est.id, ativo)
                linhas.append({"ativo": ativo, "estrategia": est.nome, "id": est.id, "erro": str(e)})
                continue
            corte_data = df["datetime"].iat[wf["corte"]] if "datetime" in df else int(df["epoch"].iat[wf["corte"]])
            linhas.append(
                {
                    "ativo": ativo,
                    "estrategia": est.nome,
                    "id": est.id,
                    "params_escolhidos": ", ".join(f"{k}={v}" for k, v in wf["params"].items()) or "(sem parâmetros)",
                    "combinacoes_testadas": wf["combinacoes"],
                    "inicio_teste": corte_data,
                    **_linha_stats("treino", wf["treino"]),
                    **_linha_stats("teste", wf["teste"]),
                    "erro": "",
                }
            )
    return pd.DataFrame(linhas)


def relatorio(wf: pd.DataFrame, cfg: bt.ConfigBacktest, min_ops: int, info: str = "") -> tuple[pd.DataFrame, str]:
    """Resumo por estratégia: passa em TODOS os pares no teste?"""
    be = break_even(cfg.payout)
    ok = wf[wf["erro"].fillna("") == ""] if "erro" in wf else wf
    pares = sorted(wf["ativo"].unique())
    linhas = []
    for nome, g in ok.groupby("estrategia", sort=False):
        linhas.append(
            {
                "estrategia": nome,
                "pares_testados": len(g),
                "pares_com_vantagem_no_teste": int(g["teste_vantagem"].sum()),
                "pares_com_vantagem_no_treino": int(g["treino_vantagem"].sum()),
                "pares_com_lucro_no_teste": int((g["teste_lucro"] > 0).sum()),
                "acerto_medio_teste_%": round(float(g["teste_acerto_%"].mean()), 2)
                if g["teste_acerto_%"].notna().any()
                else None,
                "pior_ic95_inf_teste_%": round(float(g["teste_ic95_inf_%"].min()), 2)
                if g["teste_ic95_inf_%"].notna().any()
                else None,
                "ops_teste_total": int(g["teste_ops"].sum()),
                "lucro_teste_total": round(float(g["teste_lucro"].sum()), 2),
                "PASSA_EM_TODOS": bool(len(g) == len(pares) and g["teste_vantagem"].all()),
            }
        )
    resumo = pd.DataFrame(linhas).sort_values(
        ["PASSA_EM_TODOS", "pares_com_vantagem_no_teste", "acerto_medio_teste_%"], ascending=[False, False, False]
    )
    passam = resumo[resumo["PASSA_EM_TODOS"]]["estrategia"].tolist()

    # efeito de seleção: a melhor no treino de cada par, e como ela foi no teste
    selecao = []
    for ativo, g in ok.groupby("ativo"):
        g = g.assign(_nota=g["treino_ic95_inf_%"].fillna(-1) - 100 * be + 1000 * (g["treino_decididas"] >= min_ops))
        top = g.sort_values("_nota", ascending=False).iloc[0]
        selecao.append(
            f"  {ativo}: escolhida no treino = {top['estrategia']} ({top['params_escolhidos']}) | "
            f"treino {top['treino_acerto_%']}% (IC inf {top['treino_ic95_inf_%']}%, {top['treino_decididas']} ops) "
            f"-> teste {top['teste_acerto_%']}% (IC inf {top['teste_ic95_inf_%']}%, {top['teste_decididas']} ops)"
        )

    t = []
    t.append("RELATÓRIO DE VALIDAÇÃO (walk-forward)")
    t.append("=" * 72)
    if info:
        t.append(info)
    t.append(
        f"Payout {cfg.payout:.0%} -> acerto de break-even {be:.2%}. Expiração {cfg.expiracao} vela(s). "
        f"Empate: {cfg.empate}. Sem gale."
    )
    t.append(
        f"Critério para PASSAR: no período de TESTE (dados nunca vistos na escolha) de TODOS os "
        f"{len(pares)} pares, pelo menos {min_ops} operações decididas E limite inferior do IC de Wilson 95% "
        f"acima de {be:.2%}."
    )
    t.append("")
    if passam:
        t.append(f"PASSARAM EM TODOS OS PARES ({len(passam)}): {', '.join(passam)}")
        t.append(
            "Mesmo assim: foram testadas várias estratégias e combinações; acompanhe ao vivo (resultados/"
            "sinais_ao_vivo.csv) antes de arriscar dinheiro."
        )
    else:
        t.append("NENHUMA ESTRATÉGIA PASSOU NA VALIDAÇÃO.")
        t.append("Nenhuma mostrou acerto estatisticamente acima do break-even, fora da amostra, em todos os pares.")
        t.append("Os dados NÃO comprovam assertividade para nenhuma delas com este payout.")
    t.append("")
    t.append("Por estratégia (teste = 30% final):")
    for _, r in resumo.iterrows():
        marca = "PASSA" if r["PASSA_EM_TODOS"] else "não passa"
        t.append(
            f"  [{marca:^9}] {r['estrategia']:<28} vantagem no teste em {r['pares_com_vantagem_no_teste']}/"
            f"{r['pares_testados']} pares (treino: {r['pares_com_vantagem_no_treino']}/{r['pares_testados']}), "
            f"acerto médio teste {r['acerto_medio_teste_%']}%, pior IC inf {r['pior_ic95_inf_teste_%']}%, "
            f"lucro teste {r['lucro_teste_total']}"
        )
    t.append("")
    t.append("Efeito de seleção (escolher a melhor no passado e ver o que acontece depois):")
    t.extend(selecao)
    t.append("")
    t.append("Observação: entrada simulada na abertura da vela seguinte; atraso/slippage reais não modelados.")
    return resumo, "\n".join(t)
