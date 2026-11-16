"""Ranking honesto de estratégias: janela recente x histórico, intervalo de Wilson e break-even.

Regra de "melhor do momento" (todas as condições, na JANELA recente):
  * pelo menos `min_ops` operações decididas (WIN + LOSS), e
  * limite inferior do IC de Wilson (95%) do acerto ACIMA do acerto de break-even do payout, e
  * correção de testes múltiplos: como TODAS as estratégias são testadas na mesma janela, o p-valor
    binomial (H0: acerto <= break-even) de cada uma é ajustado por Holm entre todas as testadas e precisa
    ficar abaixo de 2,5% (o mesmo nível unilateral do IC). Mais estratégias = exigência maior.
Se nenhuma passar: "sem vantagem comprovada" — não apontamos vencedora.

Ordem da lista (nunca pelo percentual bruto, que engana com poucas operações):
  1. status: vantagem comprovada > demais com ≥ MIN_OPS_AMOSTRA operações > poucos dados > sem dados/erro;
  2. limite INFERIOR do IC (o "pior caso plausível"), maior primeiro;
  3. desempate: mais operações primeiro; depois o nome.

Sempre sem martingale (gale esconde o risco e invalida a conta de break-even).
"""

from dataclasses import replace

import pandas as pd

from . import backtest as bt
from .config import (
    CONFIANCA,
    JANELA_RANKING,
    MIN_OPERACOES,
    MIN_OPS_AMOSTRA,
    MIN_OPS_FORCA,
    TAXA_MAX_PREPARO,
    Z_FORCA,
)
from .estatistica import ALFA_UNILATERAL, ajustar_p, break_even, p_valor_acima, wilson, z_duas_proporcoes
from .estrategias import ESTRATEGIAS, ultimo_valor
from .log import obter

log = obter("ranking")


def estatisticas(ops: pd.DataFrame, payout: float, min_ops: int = MIN_OPERACOES) -> dict:
    """Estatísticas de um conjunto de operações (sem gale)."""
    wins = int((ops["resultado"] == "WIN").sum())
    losses = int((ops["resultado"] == "LOSS").sum())
    n = wins + losses
    inf, sup = wilson(wins, n, CONFIANCA)
    be = break_even(payout)
    return {
        "operacoes": len(ops),
        "wins": wins,
        "losses": losses,
        "empates": int((ops["resultado"] == "EMPATE").sum()),
        "decididas": n,
        "acerto": (wins / n) if n else None,
        "ic_inf": inf if n else None,
        "ic_sup": sup if n else None,
        "lucro": round(float(ops["lucro"].sum()), 2) if len(ops) else 0.0,
        "vantagem": bool(n >= min_ops and inf > be),
    }


def comparar_forca(janela: dict, anterior: dict) -> dict:
    """Compara a janela recente com o histórico ANTERIOR a ela (amostras independentes).
    Teste z de duas proporções, unilateral a 5%."""
    nj, na = janela["decididas"], anterior["decididas"]
    if nj < MIN_OPS_FORCA or na < MIN_OPS_FORCA:
        return {"estado": "dados insuficientes", "z": None}
    z = z_duas_proporcoes(janela["wins"], nj, anterior["wins"], na)
    if z is None:
        return {"estado": "estável", "z": None}
    estado = "perdendo força" if z < -Z_FORCA else "ganhando força" if z > Z_FORCA else "estável"
    return {"estado": estado, "z": round(z, 2)}


SELOS = {
    "comprovada": "Vantagem comprovada",
    "perdendo": "Perdendo força",
    "abaixo": "Abaixo do mínimo",  # entre MIN_OPS_AMOSTRA e min_ops operações
    "poucos": "Poucos dados",  # menos de MIN_OPS_AMOSTRA operações (amostra pequena)
    "sem": "Sem vantagem",
}


def selo(janela: dict | None, forca: dict | None, min_ops: int = MIN_OPERACOES) -> dict:
    """Selo em linguagem simples para a tela. A ordem importa: 'comprovada' só com a regra completa
    (≥ min_ops e IC acima do break-even, já calculada em `janela['vantagem']`)."""
    janela = janela or {}
    n = janela.get("decididas") or 0
    if n < MIN_OPS_AMOSTRA:
        codigo = "poucos"
    elif janela.get("vantagem"):
        codigo = "comprovada"
    elif forca and forca.get("estado") == "perdendo força":
        codigo = "perdendo"
    elif n < min_ops:
        codigo = "abaixo"
    else:
        codigo = "sem"
    return {
        "codigo": codigo,
        "texto": SELOS[codigo],
        "amostra_pequena": n < MIN_OPS_AMOSTRA,
        "perdendo_forca": bool(forca and forca.get("estado") == "perdendo força"),
    }


def preparo_informativo(taxa: float | None) -> bool:
    """ "Se formando" só é informação quando o sinal é raro. Uma estratégia que dá sinal em quase toda vela
    (ex.: Seguir cor, ~97% das velas) estaria "se formando 100%" o tempo todo: isso não diz nada."""
    return taxa is not None and taxa <= TAXA_MAX_PREPARO


def status(linha: dict) -> int:
    """0 = comprovada, 1 = demais com amostra, 2 = poucos dados, 3 = sem dados/erro (ordem da lista)."""
    j = linha.get("janela")
    if not j or not j.get("decididas"):
        return 3
    if j.get("vantagem"):
        return 0
    return 1 if j["decididas"] >= MIN_OPS_AMOSTRA else 2


def chave_ordem(linha: dict) -> tuple:
    """Status, depois limite inferior do IC (maior primeiro), depois mais operações, depois o nome."""
    j = linha.get("janela") or {}
    return (status(linha), -(j.get("ic_inf") or 0.0), -(j.get("decididas") or 0), linha.get("nome", ""))


def corrigir_multiplos(linhas: list[dict], be: float, min_ops: int) -> None:
    """Ajusta (no lugar) a vantagem de cada linha pela correção de Holm entre TODAS as estratégias testadas.
    A vantagem só continua valendo se a regra simples (≥ min_ops e IC acima do break-even) E o p-valor
    ajustado < ALFA_UNILATERAL valerem. Estratégias com erro contam como testes (p = 1): conservador."""
    pvals = []
    for l in linhas:
        j = l.get("janela") or {}
        pvals.append(p_valor_acima(j.get("wins") or 0, j.get("decididas") or 0, be))
    ajustados = ajustar_p(pvals, "holm")
    for l, p, p_aj in zip(linhas, pvals, ajustados, strict=True):
        j = l.get("janela")
        if not j:
            continue
        j["p_valor"], j["p_holm"] = p, p_aj
        j["vantagem_simples"] = j["vantagem"]
        j["vantagem"] = bool(j["vantagem"] and p_aj < ALFA_UNILATERAL)
        l["selo"] = selo(j, l.get("forca"), min_ops)


def calcular_ranking(
    df: pd.DataFrame,
    cfg: bt.ConfigBacktest,
    janela: int = JANELA_RANKING,
    min_ops: int = MIN_OPERACOES,
    estrategias=None,
    params: dict | None = None,
    elegiveis: set | None = None,
    ao_progresso=None,
) -> dict:
    """Ranking de todas as estratégias em `df` (velas FECHADAS).

    `elegiveis`: ids que podem ser escolhidos como "melhor" (ex.: as marcadas na tela). None = todas.
    `ao_progresso(feitas, total, nome)`: chamado depois de cada estratégia (tela de carregamento).
    Devolve também o último sinal de cada estratégia e a taxa de sinal (fração das velas da janela com
    sinal), que diz se o "se formando" da estratégia é informativo (ver TAXA_MAX_PREPARO)."""
    estrategias = estrategias or ESTRATEGIAS
    params = params or {}
    cfg = replace(cfg, gales=0)
    be = break_even(cfg.payout)
    inicio_janela = max(0, len(df) - int(janela))
    linhas = []
    for k, est in enumerate(estrategias):
        if ao_progresso:
            ao_progresso(k, len(estrategias), est.nome)
        p = params.get(est.id, {})
        try:
            sinais = est.gerar_sinais(df, **p)
            ops = bt.executar(df, sinais, cfg).operacoes
        except Exception as e:
            log.exception("Estratégia %s falhou no ranking", est.id)
            linhas.append(
                {
                    "id": est.id,
                    "nome": est.nome,
                    "sigla": est.sigla,
                    "erro": str(e),
                    "janela": None,
                    "historico": None,
                    "forca": None,
                    "sinal": None,
                    "selo": selo(None, None, min_ops),
                    "taxa_sinal": None,
                    "preparo_informativo": False,
                }
            )
            continue
        na_janela = ops["idx_sinal"] >= inicio_janela
        jan = estatisticas(ops[na_janela], cfg.payout, min_ops)
        hist = estatisticas(ops, cfg.payout, min_ops)
        ant = estatisticas(ops[~na_janela], cfg.payout, min_ops)
        forca = comparar_forca(jan, ant)
        recentes = sinais.iloc[inicio_janela:]
        taxa = float(recentes.isin(["CALL", "PUT"]).mean()) if len(recentes) else None
        linhas.append(
            {
                "id": est.id,
                "nome": est.nome,
                "sigla": est.sigla,
                "erro": None,
                "janela": jan,
                "historico": hist,
                "forca": forca,
                "sinal": ultimo_valor(sinais),
                "selo": selo(jan, forca, min_ops),
                "taxa_sinal": taxa,
                "preparo_informativo": preparo_informativo(taxa),
            }
        )
    if ao_progresso:
        ao_progresso(len(estrategias), len(estrategias), "")
    corrigir_multiplos(linhas, be, min_ops)

    linhas.sort(key=chave_ordem)
    melhor = next(
        (
            l["id"]
            for l in linhas
            if l["janela"] and l["janela"]["vantagem"] and (elegiveis is None or l["id"] in elegiveis)
        ),
        None,
    )
    return {
        "linhas": linhas,
        "melhor": melhor,
        "janela": int(min(janela, len(df))),
        "velas": len(df),
        "break_even": be,
        "payout": cfg.payout,
        "expiracao": cfg.expiracao,
        "min_ops": int(min_ops),
        "confianca": CONFIANCA,
        "min_ops_amostra": MIN_OPS_AMOSTRA,
        "ordem": (
            "Ordem: vantagem comprovada primeiro; depois pelo pior caso plausível (limite inferior da "
            "margem de erro), nunca pelo percentual bruto; empate: mais operações primeiro."
        ),
        "testes": len(estrategias),
        "correcao": "Holm",
        "criterio": (
            f"Melhor do momento só se, nas últimas {min(janela, len(df))} velas, tiver ≥ {min_ops} "
            f"operações E o limite inferior do IC de Wilson {CONFIANCA:.0%} do acerto ficar acima do "
            f"break-even de {be:.2%} (payout {cfg.payout:.0%}) E passar na correção de Holm para "
            f"{len(estrategias)} estratégias testadas ao mesmo tempo. Sem gale."
        ),
    }


def tabela(ranking: dict) -> pd.DataFrame:
    """Ranking em formato de tabela (para terminal/CSV)."""

    def pct(v):
        return None if v is None else round(100 * v, 2)

    linhas = []
    for l in ranking["linhas"]:
        j, h = l["janela"] or {}, l["historico"] or {}
        linhas.append(
            {
                "estrategia": l["nome"],
                "ops_janela": j.get("operacoes"),
                "acerto_janela_%": pct(j.get("acerto")),
                "ic95_janela_%": None if j.get("ic_inf") is None else f"{pct(j['ic_inf'])}–{pct(j['ic_sup'])}",
                "lucro_janela": j.get("lucro"),
                "ops_hist": h.get("operacoes"),
                "acerto_hist_%": pct(h.get("acerto")),
                "ic95_hist_%": None if h.get("ic_inf") is None else f"{pct(h['ic_inf'])}–{pct(h['ic_sup'])}",
                "lucro_hist": h.get("lucro"),
                "vantagem_comprovada": "SIM" if j.get("vantagem") else "não",
                "forca": (l["forca"] or {}).get("estado"),
                "erro": l["erro"] or "",
            }
        )
    return pd.DataFrame(linhas)
