"""Cenários SIMULADOS para ver e testar a tela sem a Deriv (http://127.0.0.1:8000/?demo=entrar).

As velas e as estatísticas são inventadas (a página mostra a faixa "DEMONSTRAÇÃO · dados simulados"),
mas passam pelas MESMAS funções do ao vivo: sinal.decidir, veredito.montar, avisos (líder e textos),
progresso.montar, mercado.analisar e scanner.pontuar. Assim os textos e as regras de honestidade da
tela são os de verdade.
"""

import time

import numpy as np
import pandas as pd

from . import mercado, progresso, scanner, sinal, veredito
from .avisos import MotorAvisos, SeletorLider, nome_ativo
from .config import JANELA_RANKING, MIN_OPERACOES, MIN_OPS_AMOSTRA, PAYOUT_PADRAO, PROGRESSO_LIMITE
from .estatistica import break_even, wilson
from .estrategias import ESTRATEGIAS, POR_ID
from .ranking import chave_ordem, selo
from .timeframes import linhas_ohlc

ID = {e.sigla: e.id for e in ESTRATEGIAS}  # sigla -> id (o id é o nome da função)
CENARIOS = ("entrar", "preparando", "aguardar", "conflito", "observacao")
SEG = 300  # M5


def _velas(n: int, seed: int, tendencia: float, inicio: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    fech = 1.0850 + np.cumsum(rng.normal(tendencia, 0.00018, n))
    abert = np.r_[fech[0] - 0.0001, fech[:-1]]
    alta = np.maximum(abert, fech) + rng.exponential(0.00008, n)
    baixa = np.minimum(abert, fech) - rng.exponential(0.00008, n)
    return pd.DataFrame(
        {"epoch": inicio + SEG * np.arange(n), "open": abert, "high": alta, "low": baixa, "close": fech}
    )


def _linha(est, wins: int, n: int, forca: str = "estável") -> dict:
    be = break_even(PAYOUT_PADRAO)
    inf, sup = wilson(wins, n)
    jan = {
        "operacoes": n,
        "wins": wins,
        "losses": n - wins,
        "empates": 0,
        "decididas": n,
        "acerto": wins / n if n else None,
        "ic_inf": inf if n else None,
        "ic_sup": sup if n else None,
        "lucro": round(wins * 10 * PAYOUT_PADRAO - (n - wins) * 10, 2),
        "vantagem": bool(n >= MIN_OPERACOES and inf > be),
    }
    f = {"estado": forca, "z": None}
    return {
        "id": est.id,
        "nome": est.nome,
        "sigla": est.sigla,
        "erro": None,
        "janela": jan,
        "historico": {**jan, "operacoes": n * 5, "decididas": n * 5},
        "forca": f,
        "sinal": None,
        "selo": selo(jan, f),
    }


def _ranking(comprovada: bool) -> dict:
    """(wins, n) por estratégia. Com `comprovada`, 'Tendência + recuo' passa na regra completa."""
    numeros = {
        "TEND": (200, 320) if comprovada else (118, 214),
        "BB": (58, 112),
        "ROMP": (77, 141),
        "REV": (101, 196),
        "MM": (49, 95),
        "RSI": (21, 38),
        "MHI": (88, 183),
        "PIN": (9, 17),
        "REJ": (52, 110),
        "ENG": (60, 131),
        "COR": (117, 248),
    }
    forca = {"MHI": "perdendo força"}
    linhas = [_linha(e, *numeros.get(e.sigla, (40, 90)), forca.get(e.sigla, "estável")) for e in ESTRATEGIAS]
    linhas.sort(key=chave_ordem)
    be = break_even(PAYOUT_PADRAO)
    melhor = next((x["id"] for x in linhas if x["janela"]["vantagem"]), None)
    return {
        "linhas": linhas,
        "melhor": melhor,
        "janela": JANELA_RANKING,
        "velas": 3000,
        "break_even": be,
        "payout": PAYOUT_PADRAO,
        "expiracao": 1,
        "min_ops": MIN_OPERACOES,
        "confianca": 0.95,
        "min_ops_amostra": MIN_OPS_AMOSTRA,
        "ordem": (
            "Ordem: vantagem comprovada primeiro; depois pelo pior caso plausível (limite inferior da "
            "margem de erro), nunca pelo percentual bruto; empate: mais operações primeiro."
        ),
        "criterio": f"(demonstração) mesma regra do ao vivo: ≥ {MIN_OPERACOES} operações e limite inferior "
        f"do IC 95% acima do break-even de {be:.2%}.",
    }


def mensagens(cenario: str, agora: float | None = None) -> list[dict]:
    """Mensagens simuladas de um cenário, no mesmo formato do ao vivo."""
    if cenario not in CENARIOS:
        raise ValueError(f"cenário desconhecido: {cenario}")
    agora = agora or time.time()
    fecha_em = int(agora) + SEG - 14  # vela começou há 14 s (dá para ver a janela de entrada)
    inicio = fecha_em - SEG * 241
    tendencia = {"entrar": 0.00006, "preparando": 0.00005, "conflito": 0.00004}.get(cenario, 0.0)
    df = _velas(241, seed={"aguardar": 11, "observacao": 4}.get(cenario, 7), tendencia=tendencia, inicio=inicio)
    fechadas, formando = df.iloc[:-1].reset_index(drop=True), df.iloc[-1:].reset_index(drop=True)
    analise = mercado.analisar(fechadas, formando, nome="EUR/USD M5")

    comprovada = cenario in ("entrar", "preparando", "conflito")
    rk = _ranking(comprovada)
    seletor = SeletorLider()
    seletor.atualizar(rk, None)
    rk = {
        **rk,
        "lider": seletor.atual,
        "lider_info": {"desafiante": None, "contagem": 0, "confirmacao": 3, "margem_ic": seletor.margem_ic},
    }
    ativas = {e.id for e in ESTRATEGIAS}
    sinais: dict = {}
    if cenario == "entrar":
        sinais = {"TEND": "CALL", "ROMP": "CALL", "COR": "PUT"}  # COR discorda, mas está abaixo do break-even
    elif cenario == "conflito":
        sinais = {"TEND": "CALL", "ROMP": "PUT"}  # ROMP: ≥ 30 ops e acerto acima do break-even
    sinais = {ID[k]: v for k, v in sinais.items()}

    # progresso de formação (condições simuladas, fórmula e textos reais)
    def prog(sigla, lado, oks, dist):
        est = POR_ID[ID[sigla]]
        conds = est.gerar_condicoes(fechadas)
        textos = [c.texto_call if lado == "CALL" else c.texto_put for c in conds]
        return progresso.montar(est, lado, oks, dist, textos)

    p_lider = None
    if cenario == "preparando":
        p_lider = prog("TEND", "CALL", [True, True, False], 0.12)
    elif cenario in ("entrar", "conflito"):
        p_lider = prog("TEND", "CALL", [True, False, False], None)
    elif cenario == "observacao":
        cand = veredito.candidata(rk, ativas)
        assert cand is not None
        p_lider = prog(
            cand["sigla"], "PUT", [True] * (len(POR_ID[cand["id"]].gerar_condicoes(fechadas)) - 1) + [False], 0.2
        )
    parciais = {"BB": ("PUT", 1, 2), "ENG": ("CALL", 2, 3), "REV": ("PUT", 2, 3)}
    estados_lista = []
    for e in ESTRATEGIAS:
        st = {
            "id": e.id,
            "estado": "AGUARDANDO",
            "dir": None,
            "cumpridas": 0,
            "total": 1,
            "pct": None,
            "lider": e.id == seletor.atual,
            "em_operacao": False,
        }
        if sinais.get(e.id):
            st.update(estado="SINAL", dir=sinais[e.id], em_operacao=True)
        elif p_lider and p_lider["id"] == e.id:
            st.update(
                estado="FORMANDO" if p_lider["pct"] >= PROGRESSO_LIMITE else "PARCIAL",
                dir=p_lider["dir"],
                cumpridas=p_lider["cumpridas"],
                total=p_lider["total"],
                pct=p_lider["pct"],
            )
        elif e.sigla in parciais:
            lado, k, n = parciais[e.sigla]
            st.update(estado="PARCIAL", dir=lado, cumpridas=k, total=n)
        estados_lista.append(st)
    estados = {s["id"]: s for s in estados_lista}
    formando_lider = (
        {seletor.atual: p_lider["dir"]}
        if seletor.atual and p_lider and p_lider["id"] == seletor.atual and p_lider["pct"] >= PROGRESSO_LIMITE
        else {}
    )
    dec = sinal.decidir(rk, sinais, formando_lider, ativas, previa=False, lider=seletor.atual)
    ver = veredito.montar(dec, rk, analise.get("humano"), cenario == "observacao", estados, ativas, p_lider)

    motor = MotorAvisos(avisar_obs=True)
    vela = int(formando["epoch"].iat[0])
    lista_avisos = (
        motor.fechamento(ver, vela, nome_ativo("frxEURUSD"))
        if cenario in ("entrar", "conflito")
        else motor.formacao(ver, p_lider, vela, nome_ativo("frxEURUSD"))
    )

    # histórico de setas: algumas da líder e de outras estratégias
    rng = np.random.default_rng(3)
    marcas = []
    for i in rng.choice(np.arange(20, len(fechadas) - 2), 26, replace=False):
        est = ESTRATEGIAS[int(rng.integers(0, len(ESTRATEGIAS)))]
        marcas.append(
            {"t": int(fechadas["epoch"].iat[i]), "id": est.id, "dir": "CALL" if rng.random() < 0.5 else "PUT"}
        )
    for i in (190, 205, 221, 233):
        marcas.append({"t": int(fechadas["epoch"].iat[i]), "id": ID["TEND"], "dir": "CALL"})

    # Top 3: análise real de 3 séries simuladas; a pontuação usa a regra real (scanner.pontuar)
    itens = []
    for k, (sim, seed, tnd) in enumerate(
        (("frxEURUSD", 7, tendencia or 0.00003), ("frxGBPJPY", 21, -0.00005), ("frxAUDUSD", 33, 0.0))
    ):
        d = df if k == 0 else _velas(241, seed, tnd, inicio).iloc[:-1]
        r_ativo = rk if (k == 0 and comprovada) else None
        itens.append(scanner.montar_item(sim, d, mercado.analisar(d), r_ativo, True))
    itens = scanner.ordenar(itens)

    # operações já resolvidas nesta sessão (bolinhas de WIN/LOSS)
    ops = []
    for n, (est_id, res) in enumerate(
        (
            ("TEND", "WIN"),
            ("ROMP", "LOSS"),
            ("TEND", "WIN"),
            ("COR", "LOSS"),
            ("TEND", "WIN"),
            ("REV", "WIN"),
            ("TEND", "LOSS"),
        ),
        start=1,
    ):
        est_id = ID[est_id]
        t = int(fechadas["epoch"].iat[-30 + 3 * n])
        nome = next(e.nome for e in ESTRATEGIAS if e.id == est_id)
        ops.append(
            {
                "tipo": "sinal",
                "op": n,
                "id": est_id,
                "nome": nome,
                "dir": "CALL",
                "t": t,
                "registrado": True,
                "principal": est_id == ID["TEND"] and comprovada,
                "ativo": "frxEURUSD",
                "timeframe": "M5",
            }
        )
        ops.append({"tipo": "resultado", "op": n, "id": est_id, "resultado": res, "entrada": 1.0851, "saida": 1.0853})

    return [
        {"tipo": "conexao", "estado": "conectado", "texto": "Conectado à Deriv (simulado)", "quedas": 0},
        {"tipo": "status", "texto": "Demonstração: dados simulados", "nivel": "ok"},
        {
            "tipo": "historico",
            "simbolo": "frxEURUSD",
            "timeframe": "M5",
            "seg": SEG,
            "expiracao": 1,
            "payout": PAYOUT_PADRAO,
            "casas": 5,
            "janela_entrada": 60,
            "velas": linhas_ohlc(df),
            "sinais": marcas,
            "n_velas": len(fechadas),
        },
        {"tipo": "ranking", **rk},
        {"tipo": "analise", **analise},
        *ops,
        {"tipo": "decisao", **dec, "novo": False, "t": int(fechadas["epoch"].iat[-1]), "veredito": ver},
        {
            "tipo": "estado",
            "estrategias": estados_lista,
            "principal": dec,
            "veredito": ver,
            "limite": PROGRESSO_LIMITE,
            "lider": seletor.atual,
            "fecha_em": fecha_em,
            "agora": agora,
        },
        *({"tipo": "aviso", **a} for a in lista_avisos),
        {
            "tipo": "top3",
            "itens": itens,
            "todos": itens,
            "regra": scanner.REGRA,
            "timeframe": "M5",
            "atualizado": agora,
            "carregando": 0,
        },
    ]
