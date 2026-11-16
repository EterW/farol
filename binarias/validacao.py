"""Validação antes de confiar: comparativo em vários pares + walk-forward (treino 70% / teste 30%).

Walk-forward sem olhar o final:
  * TREINO: sinais e operações calculados SÓ com df[:corte]; operações precisam terminar antes do corte.
    Para cada estratégia, cada combinação de parâmetros da grade é avaliada e a melhor é escolhida
    pelo limite inferior do IC de Wilson menos o break-even (exigindo o mínimo de operações).
  * TESTE: os parâmetros escolhidos são aplicados aos 30% finais. Os indicadores podem usar velas do
    treino como aquecimento (é passado), e só contam operações com sinal a partir do corte.
Passa = no TESTE de TODOS os pares: >= min_ops operações E limite inferior do IC acima do break-even E
p-valor binomial ajustado por Holm abaixo de 2,5% (correção para TODAS as hipóteses estratégia × par
testadas fora da amostra). Bonferroni e Benjamini-Hochberg (FDR) também são reportados.
"""

from dataclasses import replace

import pandas as pd

from . import backtest as bt
from .config import FRACAO_TREINO, MIN_OPERACOES
from .estatistica import ALFA_UNILATERAL, METODOS_CORRECAO, ajustar_p, break_even, p_valor_acima
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
        f"{prefixo}_wins": st["wins"],
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
    ok = (wf[wf["erro"].fillna("") == ""] if "erro" in wf else wf).copy()
    pares = sorted(wf["ativo"].unique())
    # correção de testes múltiplos: uma hipótese por (estratégia, par) no TESTE; H0: acerto <= break-even
    m = len(ok)
    pvals = [p_valor_acima(int(w), int(n), be) for w, n in zip(ok["teste_wins"], ok["teste_decididas"], strict=True)]
    ok["teste_p"] = pvals
    for metodo in METODOS_CORRECAO:
        ok[f"teste_p_{metodo}"] = ajustar_p(pvals, metodo)
    ok["teste_vantagem_holm"] = ok["teste_vantagem"].astype(bool) & (ok["teste_p_holm"] < ALFA_UNILATERAL)
    combinacoes_total = int(ok["combinacoes_testadas"].sum()) if "combinacoes_testadas" in ok else 0
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
                "pares_significativos_holm": int(g["teste_vantagem_holm"].sum()),
                "pares_significativos_bonferroni": int(
                    (g["teste_vantagem"].astype(bool) & (g["teste_p_bonferroni"] < ALFA_UNILATERAL)).sum()
                ),
                "pares_significativos_fdr": int(
                    (g["teste_vantagem"].astype(bool) & (g["teste_p_bh"] < ALFA_UNILATERAL)).sum()
                ),
                "menor_p_bruto": round(float(g["teste_p"].min()), 4),
                "menor_p_holm": round(float(g["teste_p_holm"].min()), 4),
                "combinacoes_no_treino": int(g["combinacoes_testadas"].max()) if "combinacoes_testadas" in g else 1,
                "PASSA_EM_TODOS": bool(len(g) == len(pares) and g["teste_vantagem_holm"].all()),
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
        f"acima de {be:.2%} E p-valor ajustado por Holm < {ALFA_UNILATERAL:.1%}."
    )
    t.append(
        f"Testes múltiplos: {ok['estrategia'].nunique()} estratégias × {len(pares)} pares = {m} hipóteses fora da "
        f"amostra; {combinacoes_total} combinações de parâmetros avaliadas no treino (a escolha no treino não "
        "toca o teste, por isso a correção é feita sobre as hipóteses do teste)."
    )
    sig = {
        nome: int((ok["teste_vantagem"].astype(bool) & (ok[f"teste_p_{met}"] < ALFA_UNILATERAL)).sum())
        for met, nome in METODOS_CORRECAO.items()
    }
    sem_correcao = int(ok["teste_vantagem"].astype(bool).sum())
    t.append(
        f"Pares estratégia×ativo com vantagem no teste: sem correção {sem_correcao}/{m}; "
        + "; ".join(f"{nome} {v}/{m}" for nome, v in sig.items())
        + ". (Por acaso, sem correção, seriam esperados ~"
        + f"{m * ALFA_UNILATERAL:.1f} falsos positivos se nenhuma tiver vantagem real.)"
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
            f"Holm {r['pares_significativos_holm']}/{r['pares_testados']}, "
            f"menor p {r['menor_p_bruto']} (Holm {r['menor_p_holm']}), "
            f"lucro teste {r['lucro_teste_total']}"
        )
    t.append("")
    t.append("Efeito de seleção (escolher a melhor no passado e ver o que acontece depois):")
    t.extend(selecao)
    t.append("")
    t.append("Observação: entrada simulada na abertura da vela seguinte; atraso/slippage reais não modelados.")
    resumo.attrs["hipoteses"] = m
    resumo.attrs["combinacoes"] = combinacoes_total
    return resumo, "\n".join(t)
