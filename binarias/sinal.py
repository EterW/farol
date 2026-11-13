"""Sinal único: a decisão principal vem SÓ da estratégia líder (com vantagem comprovada).

Estados:
  SEM_SINAL   nenhuma estratégia com vantagem comprovada -> "sem sinal confiável", sem aviso de entrada
  AGUARDANDO  há líder, mas ela não está se formando
  PREPARANDO  a líder está se formando (progresso de formação acima do limite) ou daria sinal se a
              vela em formação fechasse agora (prévia)
  ENTRAR      a líder deu sinal na vela que fechou e nenhuma estratégia relevante discorda
  CONFLITO    a líder deu sinal, mas outra estratégia relevante sinaliza o lado oposto

"Relevante" para conflito: estratégia marcada, com >= CONFLITO_MIN_OPERACOES operações decididas na
janela e acerto (estimativa pontual) acima do break-even. Toda estratégia comprovada é relevante.
Estratégias sem evidência nenhuma não bloqueiam a entrada, mas também nunca geram a entrada.
"""

from .config import CONFLITO_MIN_OPERACOES
from .veredito import SETA

_DO_RANKING = object()  # sentinela: usar ranking["melhor"] como líder


def _pct(v):
    return "—" if v is None else f"{100 * v:.1f}%".replace(".", ",")


def _stats(linha: dict) -> dict:
    j = linha["janela"]
    return {
        "acerto": j["acerto"],
        "ic_inf": j["ic_inf"],
        "ic_sup": j["ic_sup"],
        "operacoes": j["operacoes"],
        "decididas": j["decididas"],
        "lucro": j["lucro"],
    }


def relevantes(
    ranking: dict, ativas: set | None, excluir: str | None, min_ops: int = CONFLITO_MIN_OPERACOES
) -> list[dict]:
    """Estratégias que contam para CONFLITO (marcadas, com amostra e acerto acima do break-even)."""
    be = ranking["break_even"]
    return [
        linha
        for linha in ranking["linhas"]
        if linha["id"] != excluir
        and linha["janela"]
        and (ativas is None or linha["id"] in ativas)
        and linha["janela"]["decididas"] >= min_ops
        and (linha["janela"]["acerto"] or 0) > be
    ]


def decidir(
    ranking: dict,
    sinais: dict,
    formando: dict,
    ativas: set | None = None,
    previa: bool = False,
    min_ops_conflito: int = CONFLITO_MIN_OPERACOES,
    lider=_DO_RANKING,
) -> dict:
    """Decisão principal.

    `sinais`/`formando`: {id: "CALL"|"PUT"|None}. `formando` só precisa trazer a líder (direção em que
    ela está se formando acima do limite). `lider`: id escolhido pelo SeletorLider (com histerese);
    padrão = ranking["melhor"]. Com `previa=True` (vela ainda em formação), um sinal vira no máximo
    PREPARANDO — só vela FECHADA gera ENTRAR."""
    melhor = ranking.get("melhor") if lider is _DO_RANKING else lider
    if melhor and ativas is not None and melhor not in ativas:
        melhor = None
    linha = next((x for x in ranking["linhas"] if x["id"] == melhor), None) if melhor else None
    if linha is None or not (linha.get("janela") or {}).get("vantagem"):
        return {
            "estado": "SEM_SINAL",
            "titulo": "SEM SINAL CONFIÁVEL NO MOMENTO",
            "dir": None,
            "estrategia": None,
            "nome": None,
            "opostos": [],
            "concordam": [],
            "stats": None,
            "detalhe": (
                f"Nenhuma estratégia marcada tem vantagem comprovada nas últimas {ranking['janela']} velas "
                f"(≥ {ranking['min_ops']} operações e IC {ranking['confianca']:.0%} acima do break-even "
                f"de {_pct(ranking['break_even'])})."
            ),
        }
    base = {"estrategia": melhor, "nome": linha["nome"], "stats": _stats(linha), "opostos": [], "concordam": []}
    j = linha["janela"]
    stats_txt = (
        f"{linha['nome']}: acerto {_pct(j['acerto'])} (IC {_pct(j['ic_inf'])}–{_pct(j['ic_sup'])}) "
        f"em {j['decididas']} operações recentes."
    )
    d = sinais.get(melhor)
    if d and not previa:
        outros = relevantes(ranking, ativas, melhor, min_ops_conflito)
        opostos = [x["nome"] for x in outros if sinais.get(x["id"]) and sinais[x["id"]] != d]
        concordam = [x["nome"] for x in outros if sinais.get(x["id"]) == d]
        if opostos:
            return {
                **base,
                "estado": "CONFLITO",
                "titulo": "CONFLITO, NÃO ENTRAR",
                "dir": d,
                "opostos": opostos,
                "concordam": concordam,
                "detalhe": f"{linha['nome']} diz {d}, mas {', '.join(opostos)} "
                f"{'diz' if len(opostos) == 1 else 'dizem'} {'PUT' if d == 'CALL' else 'CALL'}.",
            }
        return {
            **base,
            "estado": "ENTRAR",
            "titulo": f"ENTRAR AGORA {SETA[d]} {d}",
            "dir": d,
            "concordam": concordam,
            "detalhe": f"Entrada na abertura desta vela, expiração de {ranking['expiracao']} vela(s). {stats_txt}",
        }
    p = d or formando.get(melhor)
    if p:
        return {
            **base,
            "estado": "PREPARANDO",
            "titulo": f"SE PREPARANDO {SETA[p]} {p}",
            "dir": p,
            "detalhe": f"A estratégia líder está se formando e pode disparar no fechamento desta vela. {stats_txt}",
        }
    return {
        **base,
        "estado": "AGUARDANDO",
        "titulo": "AGUARDANDO SINAL",
        "dir": None,
        "detalhe": f"Estratégia líder armada para o próximo sinal. {stats_txt}",
    }
