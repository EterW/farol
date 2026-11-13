"""Cenários SIMULADOS para ver e testar a tela sem a Deriv (http://127.0.0.1:8000/?demo=entrar).

As velas e as estatísticas são inventadas (a página mostra a faixa "DEMONSTRAÇÃO · dados simulados"),
mas passam pelas MESMAS funções do ao vivo: sinal.decidir, veredito.montar, mercado.analisar e
scanner.pontuar. Assim os textos e as regras de honestidade da tela são os de verdade.
"""
import time

import numpy as np
import pandas as pd

from . import mercado, scanner, sinal, veredito
from .config import JANELA_RANKING, MIN_OPERACOES, PAYOUT_PADRAO
from .estatistica import break_even, wilson
from .estrategias import ESTRATEGIAS
from .ranking import selo

ID = {e.sigla: e.id for e in ESTRATEGIAS}   # sigla -> id (o id é o nome da função)
CENARIOS = ("entrar", "preparando", "aguardar", "conflito", "observacao")
SEG = 300   # M5


def _velas(n: int, seed: int, tendencia: float, inicio: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    fech = 1.0850 + np.cumsum(rng.normal(tendencia, 0.00018, n))
    abert = np.r_[fech[0] - 0.0001, fech[:-1]]
    alta = np.maximum(abert, fech) + rng.exponential(0.00008, n)
    baixa = np.minimum(abert, fech) - rng.exponential(0.00008, n)
    return pd.DataFrame({"epoch": inicio + SEG * np.arange(n), "open": abert, "high": alta,
                         "low": baixa, "close": fech})


def _linha(est, wins: int, n: int, forca: str = "estável") -> dict:
    be = break_even(PAYOUT_PADRAO)
    inf, sup = wilson(wins, n)
    jan = {"operacoes": n, "wins": wins, "losses": n - wins, "empates": 0, "decididas": n,
           "acerto": wins / n if n else None, "ic_inf": inf if n else None, "ic_sup": sup if n else None,
           "lucro": round(wins * 10 * PAYOUT_PADRAO - (n - wins) * 10, 2),
           "vantagem": bool(n >= MIN_OPERACOES and inf > be)}
    f = {"estado": forca, "z": None}
    return {"id": est.id, "nome": est.nome, "sigla": est.sigla, "erro": None, "janela": jan,
            "historico": {**jan, "operacoes": n * 5, "decididas": n * 5}, "forca": f,
            "sinal": None, "preparo": None, "selo": selo(jan, f)}


def _ranking(comprovada: bool) -> dict:
    """(wins, n) por estratégia. Com `comprovada`, 'Tendência + recuo' passa na regra completa."""
    numeros = {
        "TEND": (200, 320) if comprovada else (118, 214),
        "BB": (58, 112), "ROMP": (77, 141), "REV": (101, 196), "MM": (49, 95),
        "RSI": (21, 38), "MHI": (88, 183), "PIN": (9, 17), "REJ": (52, 110), "ENG": (60, 131), "COR": (117, 248),
    }
    forca = {"MHI": "perdendo força"}
    linhas = [_linha(e, *numeros.get(e.sigla, (40, 90)), forca.get(e.sigla, "estável")) for e in ESTRATEGIAS]
    linhas.sort(key=lambda l: (0 if l["janela"]["vantagem"] else 1, -(l["janela"]["ic_inf"] or 0)))
    be = break_even(PAYOUT_PADRAO)
    melhor = next((l["id"] for l in linhas if l["janela"]["vantagem"]), None)
    return {"linhas": linhas, "melhor": melhor, "janela": JANELA_RANKING, "velas": 3000, "break_even": be,
            "payout": PAYOUT_PADRAO, "expiracao": 1, "min_ops": MIN_OPERACOES, "confianca": 0.95,
            "criterio": f"(demonstração) mesma regra do ao vivo: ≥ {MIN_OPERACOES} operações e limite inferior "
                        f"do IC 95% acima do break-even de {be:.2%}."}


def _linhas_json(df: pd.DataFrame) -> list[list]:
    return [[int(r.epoch), float(r.open), float(r.high), float(r.low), float(r.close)] for r in df.itertuples()]


def mensagens(cenario: str, agora: float | None = None) -> list[dict]:
    if cenario not in CENARIOS:
        raise ValueError(f"cenário desconhecido: {cenario}")
    agora = agora or time.time()
    fecha_em = int(agora) + SEG - 14   # vela começou há 14 s (dá para ver a janela de entrada)
    inicio = fecha_em - SEG * 241
    tendencia = {"entrar": 0.00006, "preparando": 0.00005, "conflito": 0.00004}.get(cenario, 0.0)
    df = _velas(241, seed={"aguardar": 11, "observacao": 4}.get(cenario, 7), tendencia=tendencia, inicio=inicio)
    fechadas, formando = df.iloc[:-1].reset_index(drop=True), df.iloc[-1:].reset_index(drop=True)
    analise = mercado.analisar(fechadas, formando, nome="EUR/USD M5")

    comprovada = cenario in ("entrar", "preparando", "conflito")
    rk = _ranking(comprovada)
    sinais, preparo = {}, {}
    if cenario == "entrar":
        sinais = {"TEND": "CALL", "ROMP": "CALL", "COR": "PUT"}   # COR discorda, mas está abaixo do break-even
    elif cenario == "preparando":
        preparo = {"TEND": "CALL", "ROMP": "CALL"}
    elif cenario == "conflito":
        sinais = {"TEND": "CALL", "ROMP": "PUT"}                     # ROMP: ≥ 30 ops e acerto acima do break-even
    elif cenario == "observacao":
        preparo = {"TEND": "PUT"}
    sinais = {ID[k]: v for k, v in sinais.items()}
    preparo = {ID[k]: v for k, v in preparo.items()}
    ativas = {e.id for e in ESTRATEGIAS}
    dec = sinal.decidir(rk, sinais, preparo, ativas, previa=False)
    estados_lista = []
    for e in ESTRATEGIAS:
        if sinais.get(e.id):
            st = {"id": e.id, "estado": "SINAL", "dir": sinais[e.id], "em_operacao": True}
        elif preparo.get(e.id):
            st = {"id": e.id, "estado": "SE PREPARANDO", "dir": preparo[e.id], "em_operacao": False}
        else:
            st = {"id": e.id, "estado": "AGUARDANDO", "dir": None, "em_operacao": False}
        estados_lista.append(st)
    estados = {s["id"]: s for s in estados_lista}
    ver = veredito.montar(dec, rk, analise.get("humano"), cenario == "observacao", estados, ativas)

    # histórico de setas: algumas da líder e de outras estratégias
    rng = np.random.default_rng(3)
    marcas = []
    for i in rng.choice(np.arange(20, len(fechadas) - 2), 26, replace=False):
        est = ESTRATEGIAS[int(rng.integers(0, len(ESTRATEGIAS)))]
        marcas.append({"t": int(fechadas["epoch"].iat[i]), "id": est.id, "dir": "CALL" if rng.random() < .5 else "PUT"})
    for i in (190, 205, 221, 233):
        marcas.append({"t": int(fechadas["epoch"].iat[i]), "id": ID["TEND"], "dir": "CALL"})

    # Top 3: análise real de 3 séries simuladas; a pontuação usa a regra real (scanner.pontuar)
    itens = []
    for k, (sim, seed, tnd) in enumerate((("frxEURUSD", 7, tendencia or 0.00003), ("frxGBPJPY", 21, -0.00005),
                                          ("frxAUDUSD", 33, 0.0))):
        d = df if k == 0 else _velas(241, seed, tnd, inicio).iloc[:-1]
        a = mercado.analisar(d)
        r_ativo = rk if (k == 0 and comprovada) else None
        pts = scanner.pontuar(a, r_ativo, True)
        melhor = None
        if r_ativo:
            l = next(x for x in rk["linhas"] if x["id"] == rk["melhor"])
            melhor = {"id": l["id"], "nome": l["nome"], "acerto": l["janela"]["acerto"],
                      "ic_inf": l["janela"]["ic_inf"], "operacoes": l["janela"]["operacoes"]}
        itens.append({"simbolo": sim, "aberto": True, **pts, "tendencia": a.get("tendencia"),
                      "forca": a.get("forca"), "adx": a.get("adx"), "atr_percentil": a.get("atr_percentil"),
                      "volatilidade": a.get("volatilidade"), "melhor_estrategia": melhor, "velas": len(d),
                      "resumo": a.get("resumo"), "porque": scanner.porque(a, pts["componentes"], melhor),
                      "spark": [float(x) for x in d["close"].tail(scanner.N_SPARK)]})
    itens = scanner.ordenar(itens)

    # operações já resolvidas nesta sessão (bolinhas de WIN/LOSS)
    ops = []
    for n, (est_id, res) in enumerate((("TEND", "WIN"), ("ROMP", "LOSS"), ("TEND", "WIN"), ("COR", "LOSS"),
                                       ("TEND", "WIN"), ("REV", "WIN"), ("TEND", "LOSS")), start=1):
        est_id = ID[est_id]
        t = int(fechadas["epoch"].iat[-30 + 3 * n])
        nome = next(e.nome for e in ESTRATEGIAS if e.id == est_id)
        ops.append({"tipo": "sinal", "op": n, "id": est_id, "nome": nome, "dir": "CALL", "t": t, "registrado": True,
                    "principal": est_id == ID["TEND"] and comprovada, "ativo": "frxEURUSD"})
        ops.append({"tipo": "resultado", "op": n, "id": est_id, "resultado": res, "entrada": 1.0851, "saida": 1.0853})

    return [
        {"tipo": "conexao", "estado": "conectado", "texto": "Conectado à Deriv (simulado)", "quedas": 0},
        {"tipo": "status", "texto": "Demonstração: dados simulados", "nivel": "ok"},
        {"tipo": "historico", "simbolo": "frxEURUSD", "timeframe": "M5", "seg": SEG, "expiracao": 1,
         "payout": PAYOUT_PADRAO, "casas": 5, "janela_entrada": 60, "velas": _linhas_json(df), "sinais": marcas, "n_velas": len(fechadas)},
        {"tipo": "ranking", **rk},
        {"tipo": "analise", **analise},
        *ops,
        {"tipo": "decisao", **dec, "novo": False, "t": int(fechadas["epoch"].iat[-1]), "veredito": ver},
        {"tipo": "estado", "estrategias": estados_lista, "principal": dec, "veredito": ver,
         "fecha_em": fecha_em, "agora": agora},
        {"tipo": "top3", "itens": itens, "todos": itens, "regra": scanner.REGRA, "timeframe": "M5",
         "atualizado": agora, "carregando": 0},
    ]
