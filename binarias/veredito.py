"""Veredito em português simples para a tela principal (o que fazer AGORA).

Recebe a decisão técnica de `sinal.decidir` e a traduz para 5 estados:

  ENTRAR      só com estratégia de vantagem comprovada (≥ min_ops e IC de Wilson acima do break-even)
              E sinal na vela que acabou de fechar. Reconfere a regra aqui (defesa em profundidade).
  PREPARANDO  a estratégia líder (comprovada) está se formando: progresso de formação acima do limite.
  AGUARDAR    nada a fazer (com o motivo em uma frase).
  CONFLITO    a estratégia comprovada diz um lado e outra relevante diz o outro.
  OBSERVACAO  modo observação ligado e NENHUMA estratégia comprovada: mostra a melhor candidata,
              com o rótulo "NÃO COMPROVADA" e sem som de entrada.

`progresso` (binarias/progresso.py) vai junto no veredito da líder/candidata, para a barra de formação.

Regra de honestidade: nunca dizemos que algo "vai ganhar". Toda probabilidade é ESTIMADA a partir do
histórico recente e vem com intervalo de confiança, tamanho da amostra e break-even.
"""

from .estatistica import break_even as calc_break_even

ACAO: dict[str | None, str] = {"CALL": "COMPRA", "PUT": "VENDA"}
SETA: dict[str | None, str] = {"CALL": "▲", "PUT": "▼"}
ROTULO_OBS = "NÃO COMPROVADA · apenas observação, não é recomendação"


def _fmt(v: float, casas: int = 0) -> str:
    return f"{100 * v:.{casas}f}".replace(".", ",") + "%"


def texto_probabilidade(stats: dict | None, break_even: float, min_ops: int, janela: int | None = None) -> dict:
    """Probabilidade estimada de acerto com intervalo, amostra e break-even, e os avisos honestos.

    `stats`: dict com acerto, ic_inf, ic_sup, decididas (formato de ranking.estatisticas / sinal._stats)."""
    stats = stats or {}
    n = int(stats.get("decididas") or 0)
    be_txt = _fmt(break_even, 1)
    base = {
        "break_even": break_even,
        "break_even_txt": f"Para lucrar, precisa acertar mais de {be_txt}",
        "n": n,
        "min_ops": min_ops,
    }
    if not n or stats.get("acerto") is None:
        return {
            **base,
            "ok": False,
            "acerto": None,
            "inf": None,
            "sup": None,
            "texto": "Probabilidade estimada: sem dados (0 operações)",
            "amostra": "0 operações no histórico recente",
            "avisos": [{"codigo": "poucos", "texto": "Poucos dados: ainda não dá para estimar."}],
            "pode_nao_ter_vantagem": True,
            "poucos_dados": True,
        }
    p, inf, sup = stats["acerto"], stats["ic_inf"], stats["ic_sup"]
    # inteiros são mais fáceis de ler; usa 1 casa quando o arredondamento esconderia a diferença p/ o break-even
    casas = 1 if abs(inf - break_even) < 0.01 or abs(p - break_even) < 0.01 else 0
    onde = f" nas últimas {janela} velas" if janela else " no histórico recente"
    avisos = []
    poucos = n < min_ops
    sem_vantagem = inf <= break_even
    if poucos:
        avisos.append(
            {"codigo": "poucos", "texto": f"Poucos dados: só {n} operações (o mínimo confiável é {min_ops})."}
        )
    if sem_vantagem:
        avisos.append(
            {
                "codigo": "sem_vantagem",
                "texto": "Pode não ter vantagem real: a faixa de incerteza inclui o mínimo para lucrar.",
            }
        )
    return {
        **base,
        "ok": True,
        "acerto": p,
        "inf": inf,
        "sup": sup,
        "texto": f"Probabilidade estimada: {_fmt(p, casas)} (entre {_fmt(inf, casas)} e {_fmt(sup, casas)})",
        "curto": _fmt(p, casas),
        "faixa": f"entre {_fmt(inf, casas)} e {_fmt(sup, casas)}",
        "amostra": f"com base em {n} operações{onde}",
        "avisos": avisos,
        "pode_nao_ter_vantagem": sem_vantagem,
        "poucos_dados": poucos,
    }


def comprovada(linha: dict | None, break_even: float, min_ops: int) -> bool:
    """A regra completa de vantagem comprovada, reconferida a partir dos números."""
    j = (linha or {}).get("janela")
    return bool(
        j
        and not (linha or {}).get("controle")  # estratégia de controle (régua) nunca é líder nem gera aviso
        and j.get("vantagem")
        and (j.get("decididas") or 0) >= min_ops
        and j.get("ic_inf") is not None
        and j["ic_inf"] > break_even
    )


def candidata(ranking: dict, ativas: set | None = None) -> dict | None:
    """Melhor estratégia do momento SEM exigir vantagem (só para o modo observação).
    Usa a ordem do ranking (limite inferior do IC); prefere as marcadas, se houver alguma com dados."""
    com_dados = [
        l
        for l in ranking.get("linhas", [])
        if l.get("janela") and l["janela"].get("decididas") and not l.get("controle")
    ]
    marcadas = [l for l in com_dados if ativas is None or l["id"] in ativas]
    lista = marcadas or com_dados
    return lista[0] if lista else None


def _motivo_aguardar(humano: dict | None, observacao: bool) -> str:
    h = humano or {}
    if h.get("ok") and h.get("lateral"):
        motivo = "Mercado lateral e nenhuma estratégia com vantagem comprovada."
    elif h.get("ok") and h.get("movimento") == "Agitado":
        motivo = "Mercado agitado e nenhuma estratégia com vantagem comprovada."
    elif h.get("ok") and h.get("movimento") == "Calmo":
        motivo = "Mercado parado e nenhuma estratégia com vantagem comprovada."
    else:
        motivo = "Nenhuma estratégia tem vantagem comprovada neste ativo agora."
    if not observacao:
        motivo += " Ligue o modo observação se quiser ver a melhor candidata (sem recomendação)."
    return motivo


def montar(
    decisao: dict,
    ranking: dict,
    humano: dict | None = None,
    observacao: bool = False,
    estados: dict | None = None,
    ativas: set | None = None,
    progresso: dict | None = None,
) -> dict:
    """`decisao`: saída de sinal.decidir. `estados`: {id: {"estado": "SINAL"|"FORMANDO"|..., "dir": ...}}
    (vela atual). `progresso`: progresso de formação da líder (ou da candidata, no modo observação)."""
    be = ranking.get("break_even", calc_break_even(ranking.get("payout", 0.85)))
    min_ops = int(ranking.get("min_ops", 100))
    janela = ranking.get("janela")
    est = decisao.get("estado")
    linha = next((l for l in ranking.get("linhas", []) if l["id"] == decisao.get("estrategia")), None)
    base = {
        "estrategia": decisao.get("estrategia"),
        "nome": decisao.get("nome"),
        "dir": decisao.get("dir"),
        "acao": ACAO.get(decisao.get("dir")),
        "seta": SETA.get(decisao.get("dir"), ""),
        "break_even": be,
        "min_ops": min_ops,
        "janela": janela,
        "expiracao": ranking.get("expiracao", 1),
        "detalhe": decisao.get("detalhe", ""),
        "opostos": decisao.get("opostos", []),
        "concordam": decisao.get("concordam", []),
        "rotulo": None,
        "som": None,
        "comprovada": False,
        "prob": None,
        "quando": None,
        "progresso": progresso if progresso and progresso.get("id") == decisao.get("estrategia") else None,
    }

    if est in ("ENTRAR", "PREPARANDO", "CONFLITO", "AGUARDANDO"):
        if not comprovada(linha, be, min_ops):
            # nunca deveria acontecer (sinal.decidir só usa a "melhor"), mas a tela não pode mentir
            return {
                **base,
                "estado": "AGUARDAR",
                "titulo": "AGUARDAR",
                "dir": None,
                "acao": None,
                "seta": "",
                "frase": "Sinal ignorado: a estratégia não tem vantagem comprovada.",
            }
        assert linha is not None  # garantido por comprovada()
        stats = linha["janela"]
        base = {**base, "comprovada": True, "prob": texto_probabilidade(stats, be, min_ops, janela)}

    if est == "ENTRAR":
        d = decisao["dir"]
        exp = base["expiracao"]
        return {
            **base,
            "estado": "ENTRAR",
            "titulo": "ENTRAR AGORA",
            "som": "entrada",
            "frase": f"Entre em {ACAO[d]} {SETA[d]} na abertura desta vela. "
            f"Expiração: {exp} vela{'s' if exp > 1 else ''}.",
        }
    if est == "PREPARANDO":
        d = decisao["dir"]
        return {
            **base,
            "estado": "PREPARANDO",
            "titulo": "SE PREPARANDO",
            "som": "formando",
            "quando": "formando",
            "frase": f"“{decisao['nome']}” está se formando e pode indicar {ACAO[d]} {SETA[d]} quando esta "
            "vela fechar. Ainda não entre: espere a confirmação.",
        }
    if est == "CONFLITO":
        d = decisao["dir"]
        outro = "VENDA" if d == "CALL" else "COMPRA"
        verbo = "indicam" if len(decisao.get("opostos", [])) > 1 else "indica"
        quem = ", ".join(f"“{n}”" for n in decisao.get("opostos", []))
        return {
            **base,
            "estado": "CONFLITO",
            "titulo": "CONFLITO, NÃO ENTRAR",
            "frase": f"“{decisao['nome']}” indica {ACAO[d]}, mas {quem} {verbo} {outro}. "
            "Quando as estratégias discordam, o melhor é ficar de fora.",
        }
    if est == "AGUARDANDO":
        return {
            **base,
            "estado": "AGUARDAR",
            "titulo": "AGUARDAR",
            "dir": None,
            "acao": None,
            "seta": "",
            "frase": f"A estratégia líder (“{decisao['nome']}”) tem vantagem comprovada, mas ainda não está "
            "se formando. Nada a fazer por enquanto.",
        }

    # SEM_SINAL: nenhuma estratégia comprovada
    cand = candidata(ranking, ativas) if observacao else None
    if not cand:
        return {
            **base,
            "estado": "AGUARDAR",
            "titulo": "AGUARDAR",
            "estrategia": None,
            "nome": None,
            "dir": None,
            "acao": None,
            "seta": "",
            "frase": _motivo_aguardar(humano, observacao),
        }
    st = (estados or {}).get(cand["id"]) or {}
    d = st.get("dir") if st.get("estado") in ("SINAL", "FORMANDO") else None
    quando = None
    if d:
        quando = "agora" if st["estado"] == "SINAL" else "formando"
        txt = "agora" if quando == "agora" else "quando esta vela fechar (está se formando)"
        frase = f"Melhor candidata do momento: “{cand['nome']}”. Ela indicaria {ACAO[d]} {SETA[d]} {txt}."
    else:
        frase = f"Melhor candidata do momento: “{cand['nome']}”. Ela não está indicando nada agora."
    # (só acontece se o usuário desmarcou a estratégia comprovada e nenhuma marcada tem dados)
    desmarcada = comprovada(cand, be, min_ops)
    return {
        **base,
        "estado": "OBSERVACAO",
        "titulo": "MODO OBSERVAÇÃO",
        "estrategia": cand["id"],
        "nome": cand["nome"],
        "dir": d,
        "acao": ACAO.get(d),
        "seta": SETA.get(d, ""),
        "rotulo": "DESMARCADA POR VOCÊ · apenas observação, não é recomendação" if desmarcada else ROTULO_OBS,
        "som": None,
        "comprovada": False,
        "quando": quando,
        "progresso": progresso if progresso and progresso.get("id") == cand["id"] else None,
        "prob": texto_probabilidade(cand["janela"], be, min_ops, janela),
        "frase": frase + " Nenhuma estratégia tem vantagem comprovada agora.",
    }
