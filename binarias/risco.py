"""Gerenciamento de risco ("Minha banca"): contas puras, testáveis. SEM martingale (valor de entrada fixo).

Os dados da banca e do diário ficam SÓ no navegador; ele manda os números para estas contas no servidor
local (127.0.0.1) e nada é gravado aqui.

Verdade que nenhuma gestão muda: com acerto abaixo do break-even 1/(1+payout), o resultado esperado de cada
operação é negativo, então o resultado esperado de qualquer sequência também é. Gestão só controla o
tamanho do estrago e o risco de quebrar, não cria vantagem.
"""

from __future__ import annotations

import numpy as np

from .estatistica import break_even

PCT_PADRAO = (1.0, 2.0)  # faixa recomendada de % da banca por operação
PCT_ALERTA = 5.0  # acima disso: aviso forte
PERDA_DIA_PADRAO = 5.0  # % da banca do início do dia
PARAR_APOS_PADRAO = 3  # losses seguidos
MAX_SIMULACOES = 20000
MAX_OPERACOES_SIM = 2000

AVISO_BREAK_EVEN = (
    "Com acerto abaixo do break-even, o resultado esperado é prejuízo em QUALQUER gestão de banca. "
    "Gestão controla o risco; não cria vantagem."
)


def _num(v, nome: str, minimo: float | None = None, maximo: float | None = None) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{nome} precisa ser um número") from None
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError(f"{nome} inválido")
    if minimo is not None and x < minimo:
        raise ValueError(f"{nome} deve ser ≥ {minimo:g}")
    if maximo is not None and x > maximo:
        raise ValueError(f"{nome} deve ser ≤ {maximo:g}")
    return x


def valor_entrada(banca: float, pct: float) -> dict:
    """Valor sugerido por operação (fração fixa da banca) e os avisos sobre o % escolhido."""
    banca = _num(banca, "banca", 0)
    pct = _num(pct, "% por operação", 0, 100)
    avisos = []
    if pct > PCT_ALERTA:
        avisos.append(
            {
                "nivel": "alto",
                "texto": f"{pct:g}% por operação é arriscado: acima de {PCT_ALERTA:g}%, poucas perdas seguidas "
                "derrubam a banca.",
            }
        )
    elif pct > PCT_PADRAO[1]:
        avisos.append({"nivel": "medio", "texto": f"Acima do comum ({PCT_PADRAO[0]:g}% a {PCT_PADRAO[1]:g}%)."})
    return {"valor": round(banca * pct / 100, 2), "pct": pct, "avisos": avisos}


def resultado_operacao(resultado: str, valor: float, payout: float) -> float:
    """Lucro/prejuízo de UMA operação binária: WIN = valor × payout; LOSS = −valor; EMPATE = 0."""
    valor = _num(valor, "valor", 0)
    payout = _num(payout, "payout", 0, 5)
    r = str(resultado).upper()
    if r == "WIN":
        return round(valor * payout, 2)
    if r == "LOSS":
        return -round(valor, 2)
    if r == "EMPATE":
        return 0.0
    raise ValueError("resultado deve ser WIN, LOSS ou EMPATE")


def estado_dia(
    banca_inicio: float,
    operacoes: list[dict],
    perda_max_pct: float = PERDA_DIA_PADRAO,
    parar_apos: int = PARAR_APOS_PADRAO,
    meta_pct: float | None = None,
) -> dict:
    """Situação do dia: resultado, distância até o limite de perda e bloqueio ("pare por hoje").

    `operacoes`: [{"resultado": "WIN"|"LOSS"|"EMPATE", "valor": 10, "payout": 0.85}, ...] na ordem do dia.
    Bloqueia quando a perda do dia chega ao limite OU quando há `parar_apos` losses seguidos (0 = desligado)."""
    banca_inicio = _num(banca_inicio, "banca do início do dia", 0)
    perda_max_pct = _num(perda_max_pct, "perda máxima do dia", 0, 100)
    parar_apos = int(_num(parar_apos, "parar após N losses", 0, 100))
    meta = None if meta_pct in (None, "", 0) else _num(meta_pct, "meta do dia", 0, 1000)
    resultado, seguidos, wins, losses, empates = 0.0, 0, 0, 0, 0
    for op in operacoes or []:
        lucro = resultado_operacao(str(op.get("resultado")), op.get("valor", 0), op.get("payout", 0))
        resultado += lucro
        r = str(op.get("resultado")).upper()
        if r == "LOSS":
            seguidos += 1
            losses += 1
        elif r == "WIN":
            seguidos = 0
            wins += 1
        else:
            empates += 1  # empate não zera nem soma a sequência de losses
    resultado = round(resultado, 2)
    limite_valor = round(banca_inicio * perda_max_pct / 100, 2)
    distancia = round(limite_valor + resultado, 2)  # quanto ainda pode perder hoje (≤ 0 = atingiu)
    motivos = []
    if limite_valor > 0 and distancia <= 0:
        motivos.append(f"perda do dia chegou a {perda_max_pct:g}% da banca")
    if parar_apos and seguidos >= parar_apos:
        motivos.append(f"{seguidos} losses seguidos (limite: {parar_apos})")
    meta_valor = None if meta is None else round(banca_inicio * meta / 100, 2)
    return {
        "resultado": resultado,
        "banca_atual": round(banca_inicio + resultado, 2),
        "operacoes": wins + losses + empates,
        "wins": wins,
        "losses": losses,
        "empates": empates,
        "losses_seguidos": seguidos,
        "limite_perda": limite_valor,
        "distancia_limite": max(0.0, distancia),
        "bloqueado": bool(motivos),
        "motivo": "Limite do dia atingido: pare por hoje (" + "; ".join(motivos) + ")." if motivos else "",
        "meta": meta_valor,
        "meta_atingida": bool(meta_valor and resultado >= meta_valor),
    }


def simular(
    acerto: float,
    payout: float,
    pct: float,
    n_operacoes: int = 100,
    simulacoes: int = 5000,
    limite_ruina_pct: float = 50.0,
    semente: int | None = 12345,
) -> dict:
    """Simulador "e se" (Monte Carlo simples, valor de entrada FIXO = pct da banca inicial, sem martingale).

    Banca inicial = 100 (resultados em % da banca). Ruína aproximada = chance de, em algum momento das
    `n_operacoes`, a banca cair `limite_ruina_pct`% ou mais (ou não ter mais saldo para a entrada)."""
    p = _num(acerto, "taxa de acerto", 0, 1)
    payout = _num(payout, "payout", 0.01, 5)
    pct = _num(pct, "% por operação", 0.01, 100)
    n = int(_num(n_operacoes, "operações", 1, MAX_OPERACOES_SIM))
    sims = int(_num(simulacoes, "simulações", 100, MAX_SIMULACOES))
    lim = _num(limite_ruina_pct, "limite de ruína", 1, 100)
    be = break_even(payout)
    entrada = pct  # banca 100 -> entrada = pct
    ev_op = p * payout - (1 - p)  # em unidades da entrada
    rng = np.random.default_rng(semente)
    ganhos = rng.random((sims, n)) < p
    passos = np.where(ganhos, entrada * payout, -entrada)
    caminho = 100 + np.cumsum(passos, axis=1)
    # quem não tem saldo para a próxima entrada para de operar (fica parado onde está)
    sem_saldo = caminho < entrada
    quebrou = sem_saldo.any(axis=1)
    if quebrou.any():
        primeiro = np.where(quebrou, sem_saldo.argmax(axis=1), n - 1)
        for i in np.flatnonzero(quebrou):
            caminho[i, primeiro[i] + 1 :] = caminho[i, primeiro[i]]
    final = caminho[:, -1]
    minimo = caminho.min(axis=1)
    ruina = (minimo <= 100 - lim) | quebrou
    avisos = []
    if p <= be:
        avisos.append(AVISO_BREAK_EVEN)
    return {
        "acerto": p,
        "payout": payout,
        "break_even": be,
        "pct": pct,
        "n_operacoes": n,
        "simulacoes": sims,
        "esperado_pct_banca": round(n * entrada * ev_op, 2),  # conta exata (valor esperado), não simulação
        "esperado_por_operacao_pct": round(entrada * ev_op, 4),
        "mediana_final_pct": round(float(np.median(final)) - 100, 2),
        "p5_final_pct": round(float(np.percentile(final, 5)) - 100, 2),
        "p95_final_pct": round(float(np.percentile(final, 95)) - 100, 2),
        "prob_prejuizo": round(float((final < 100).mean()), 4),
        "prob_ruina": round(float(ruina.mean()), 4),
        "limite_ruina_pct": lim,
        "abaixo_break_even": p <= be,
        "avisos": avisos,
        "explicacao": (
            f"{sims} simulações de {n} operações com entrada fixa de {pct:g}% da banca inicial e payout de "
            f"{payout:.0%}. 'Ruína' aqui = a banca cair {lim:g}% ou mais em algum momento. A taxa de acerto é "
            "uma estimativa do passado, com margem de erro: o futuro pode ser pior."
        ),
    }
