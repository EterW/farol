"""Sinal único: a decisão principal vem SÓ da estratégia no topo do ranking (com vantagem comprovada).

Estados:
  SEM_SINAL   nenhuma estratégia com vantagem comprovada -> "sem sinal confiável", sem alerta de entrada
  AGUARDANDO  há estratégia no topo, mas ela não está armada
  PREPARANDO  a estratégia do topo está quase disparando (preparo ou prévia da vela em formação)
  ENTRAR      a estratégia do topo deu sinal na vela que fechou e ninguém relevante discorda
  CONFLITO    a estratégia do topo deu sinal, mas outra estratégia relevante sinaliza o lado oposto

"Relevante" para conflito: estratégia marcada, com >= CONFLITO_MIN_OPERACOES operações decididas na
janela e acerto (estimativa pontual) acima do break-even. Estratégias sem evidência nenhuma (ex.: perdendo
dinheiro) não bloqueiam a entrada, mas também nunca geram a entrada.
"""
from .config import CONFLITO_MIN_OPERACOES

SETA = {"CALL": "▲", "PUT": "▼"}


def _pct(v):
    return "—" if v is None else f"{100 * v:.1f}%".replace(".", ",")


def _stats(linha: dict) -> dict:
    j = linha["janela"]
    return {"acerto": j["acerto"], "ic_inf": j["ic_inf"], "ic_sup": j["ic_sup"],
            "operacoes": j["operacoes"], "decididas": j["decididas"], "lucro": j["lucro"]}


def relevantes(ranking: dict, ativas: set | None, excluir: str | None,
               min_ops: int = CONFLITO_MIN_OPERACOES) -> list[dict]:
    be = ranking["break_even"]
    return [l for l in ranking["linhas"]
            if l["id"] != excluir and l["janela"] and (ativas is None or l["id"] in ativas)
            and l["janela"]["decididas"] >= min_ops and (l["janela"]["acerto"] or 0) > be]


def decidir(ranking: dict, sinais: dict, preparo: dict, ativas: set | None = None,
            previa: bool = False, min_ops_conflito: int = CONFLITO_MIN_OPERACOES) -> dict:
    """`sinais`/`preparo`: {id: "CALL"|"PUT"|None}. Com `previa=True` (vela ainda em formação),
    um sinal vira no máximo PREPARANDO — só vela FECHADA gera ENTRAR."""
    melhor = ranking.get("melhor")
    if melhor and ativas is not None and melhor not in ativas:
        melhor = None
    if not melhor:
        return {
            "estado": "SEM_SINAL", "titulo": "SEM SINAL CONFIÁVEL NO MOMENTO", "dir": None,
            "estrategia": None, "nome": None, "opostos": [], "concordam": [], "stats": None,
            "detalhe": (f"Nenhuma estratégia marcada tem vantagem comprovada nas últimas {ranking['janela']} velas "
                        f"(≥ {ranking['min_ops']} operações e IC {ranking['confianca']:.0%} acima do break-even "
                        f"de {_pct(ranking['break_even'])})."),
        }
    linha = next(l for l in ranking["linhas"] if l["id"] == melhor)
    base = {"estrategia": melhor, "nome": linha["nome"], "stats": _stats(linha), "opostos": [], "concordam": []}
    stats_txt = (f"{linha['nome']}: acerto {_pct(linha['janela']['acerto'])} "
                 f"(IC {_pct(linha['janela']['ic_inf'])}–{_pct(linha['janela']['ic_sup'])}) "
                 f"em {linha['janela']['decididas']} operações recentes.")
    d = sinais.get(melhor)
    if d and not previa:
        outros = relevantes(ranking, ativas, melhor, min_ops_conflito)
        opostos = [l["nome"] for l in outros if sinais.get(l["id"]) and sinais[l["id"]] != d]
        concordam = [l["nome"] for l in outros if sinais.get(l["id"]) == d]
        if opostos:
            return {**base, "estado": "CONFLITO", "titulo": "CONFLITO, NÃO ENTRAR", "dir": d,
                    "opostos": opostos, "concordam": concordam,
                    "detalhe": f"{linha['nome']} diz {d}, mas {', '.join(opostos)} "
                               f"{'diz' if len(opostos) == 1 else 'dizem'} {'PUT' if d == 'CALL' else 'CALL'}."}
        return {**base, "estado": "ENTRAR", "titulo": f"ENTRAR AGORA {SETA[d]} {d}", "dir": d,
                "concordam": concordam,
                "detalhe": f"Entrada na abertura desta vela, expiração de {ranking['expiracao']} vela(s). {stats_txt}"}
    p = d or preparo.get(melhor)
    if p:
        return {**base, "estado": "PREPARANDO", "titulo": f"SE PREPARANDO {SETA[p]} {p}", "dir": p,
                "detalhe": f"A estratégia do topo pode disparar no fechamento desta vela. {stats_txt}"}
    return {**base, "estado": "AGUARDANDO", "titulo": "AGUARDANDO SINAL", "dir": None,
            "detalhe": f"Estratégia do topo armada para o próximo sinal. {stats_txt}"}
