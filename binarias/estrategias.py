"""Estratégias de entrada: o MESMO código serve ao backtest, ao ranking, à validação e ao ao vivo.

Cada estratégia é descrita por uma lista de CONDIÇÕES com nome. O sinal é, por construção,
"todas as condições cumpridas": CALL quando todas as condições de compra valem na vela, PUT quando
todas as de venda valem (as duas ao mesmo tempo = não entra). Assim o progresso de formação
(binarias/progresso.py) conta exatamente as mesmas condições que geram o sinal.

Um sinal na vela i significa: entrar na ABERTURA da vela i+1. O valor na vela i só pode depender
das velas 0..i (há um teste automático que trunca o futuro e confere).

Para criar a sua: escreva `minha_condicoes(df, **params) -> list[Condicao]`, a função de sinal
`minha(df, **params) = _de_condicoes(minha_condicoes(df, **params))` e registre em ESTRATEGIAS.
(Uma estratégia sem `condicoes` também funciona: o progresso usa o próprio sinal como condição única.)
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import product
from typing import NamedTuple

import pandas as pd

from .indicadores import bandas, cor, niveis_anteriores, rsi, sma

__all__ = ["ESTRATEGIAS", "EXPLICACAO", "POR_ID", "Condicao", "Estrategia", "ultimo_valor"]


class Condicao(NamedTuple):
    """Uma condição da estratégia, com o texto para a tela e as séries booleanas de cada lado."""

    texto_call: str
    texto_put: str
    call: pd.Series
    put: pd.Series


# --------------------------------------------------------------------------- #
# Auxiliares
# --------------------------------------------------------------------------- #
def _sinais(cond_call: pd.Series, cond_put: pd.Series) -> pd.Series:
    """Monta a Series de sinais. Se CALL e PUT forem verdadeiros na mesma vela, não entra."""
    call = cond_call.fillna(False).astype(bool)
    put = cond_put.fillna(False).astype(bool)
    s = pd.Series(None, index=cond_call.index, dtype=object)
    s[call & ~put] = "CALL"
    s[put & ~call] = "PUT"
    return s


def _todas(series: list[pd.Series], index: pd.Index) -> pd.Series:
    resultado = pd.Series(True, index=index)
    for s in series:
        resultado &= s.fillna(False).astype(bool)
    return resultado


def _de_condicoes(conds: list[Condicao]) -> pd.Series:
    """Sinal = todas as condições cumpridas (de compra -> CALL, de venda -> PUT)."""
    index = conds[0].call.index
    return _sinais(_todas([c.call for c in conds], index), _todas([c.put for c in conds], index))


def _c(texto_call: str, texto_put: str | None, call: pd.Series, put: pd.Series) -> Condicao:
    return Condicao(texto_call, texto_put or texto_call, call, put)


def _falso(df: pd.DataFrame) -> pd.Series:
    return pd.Series(False, index=df.index)


def _granularidade(df: pd.DataFrame) -> int:
    d = df["epoch"].diff()
    d = d[d > 0]
    return int(d.mode().iloc[0]) if len(d) else 60


# --------------------------------------------------------------------------- #
# Estratégias: condições + sinal
# --------------------------------------------------------------------------- #
def seguir_cor_condicoes(df):
    c = cor(df)
    return [_c("Vela verde (fecha acima da abertura)", "Vela vermelha (fecha abaixo da abertura)", c == 1, c == -1)]


def seguir_cor(df):
    """Entra na mesma cor da última vela."""
    return _de_condicoes(seguir_cor_condicoes(df))


def _rotulo_vela(k: int) -> str:
    return "Vela atual" if k == 0 else "Vela anterior" if k == 1 else f"Vela de {k} atrás"


def reversao_sequencia_condicoes(df, n=3):
    c = cor(df)
    return [_c(f"{_rotulo_vela(k)} vermelha", f"{_rotulo_vela(k)} verde", c.shift(k) == -1, c.shift(k) == 1)
            for k in range(int(n))]


def reversao_sequencia(df, n=3):
    """Após N velas seguidas da mesma cor, entra contra a sequência."""
    return _de_condicoes(reversao_sequencia_condicoes(df, n))


def cruzamento_medias_condicoes(df, rapida=5, lenta=20):
    mr, ml = sma(df["close"], rapida), sma(df["close"], lenta)
    validas = mr.notna() & ml.notna()
    base = validas & validas.shift(1, fill_value=False)
    acima, abaixo = mr > ml, mr < ml
    return [
        _c(f"Média {rapida} estava abaixo (ou igual) da média {lenta}",
           f"Média {rapida} estava acima (ou igual) da média {lenta}",
           base & ~acima.shift(1, fill_value=False), base & ~abaixo.shift(1, fill_value=False)),
        _c(f"Média {rapida} cruza para cima da média {lenta}", f"Média {rapida} cruza para baixo da média {lenta}",
           acima, abaixo),
    ]


def cruzamento_medias(df, rapida=5, lenta=20):
    """CALL quando a média rápida cruza a lenta para cima; PUT para baixo."""
    return _de_condicoes(cruzamento_medias_condicoes(df, rapida, lenta))


def rsi_reversao_condicoes(df, periodo=14, sobrecompra=70, sobrevenda=30):
    r = rsi(df["close"], int(periodo))
    ant = r.shift(1)
    return [
        _c(f"RSI estava abaixo de {sobrevenda} (sobrevenda)", f"RSI estava acima de {sobrecompra} (sobrecompra)",
           ant < sobrevenda, ant > sobrecompra),
        _c(f"RSI volta para {sobrevenda} ou mais", f"RSI volta para {sobrecompra} ou menos",
           r >= sobrevenda, r <= sobrecompra),
    ]


def rsi_reversao(df, periodo=14, sobrecompra=70, sobrevenda=30):
    """RSI (Wilder): CALL ao sair da sobrevenda, PUT ao sair da sobrecompra."""
    return _de_condicoes(rsi_reversao_condicoes(df, periodo, sobrecompra, sobrevenda))


def mhi_condicoes(df, tamanho_quadrante=5):
    tamanho_quadrante = int(tamanho_quadrante)
    if len(df) < 3:
        f = _falso(df)
        return [_c("Pelo menos 3 velas", None, f, f)]
    gran = _granularidade(df)
    posicao = (df["epoch"] // gran) % tamanho_quadrante
    c = cor(df)
    soma3 = c.rolling(3).sum()
    sem_doji = ~((c == 0).astype(int).rolling(3).sum() > 0)
    continuas = (df["epoch"] - df["epoch"].shift(2)) == 2 * gran
    fim = posicao == tamanho_quadrante - 1
    return [
        _c(f"Última vela do bloco de {tamanho_quadrante}", None, fim, fim),
        _c("Nenhuma vela parada (doji) entre as 3 últimas", None, sem_doji, sem_doji),
        _c("3 últimas velas sem buraco de horário", None, continuas, continuas),
        # maioria vermelha -> minoria verde -> CALL
        _c("Maioria vermelha nas 3 últimas (aposta na minoria verde)",
           "Maioria verde nas 3 últimas (aposta na minoria vermelha)", soma3 < 0, soma3 > 0),
    ]


def mhi(df, tamanho_quadrante=5):
    """MHI 1 (minoria): no fim de cada quadrante de 5 velas (alinhado ao horário), olha as 3
    últimas velas e entra na cor da MINORIA na 1ª vela do próximo quadrante. Se houver doji
    entre as 3, ou se faltar vela no meio (buraco de mercado), não entra."""
    return _de_condicoes(mhi_condicoes(df, tamanho_quadrante))


def tendencia_recuo_condicoes(df, periodo=50):
    ma = sma(df["close"], periodo)
    ma_ant = ma.shift(1)
    c = cor(df)
    return [
        _c(f"Fecha acima da média de {periodo}", f"Fecha abaixo da média de {periodo}",
           df["close"] > ma, df["close"] < ma),
        _c("Vela anterior recuou até a média", None, df["low"].shift(1) <= ma_ant, df["high"].shift(1) >= ma_ant),
        _c("Vela atual verde (voltou a subir)", "Vela atual vermelha (voltou a cair)", c == 1, c == -1),
    ]


def tendencia_recuo(df, periodo=50):
    """Tendência + recuo: CALL se fecha acima da média, a vela anterior tocou/cruzou a média
    e a atual fecha verde (voltou a subir). PUT no inverso."""
    return _de_condicoes(tendencia_recuo_condicoes(df, periodo))


def bollinger_rsi_condicoes(df, periodo_bb=20, desvios=2.0, periodo_rsi=14, sobrecompra=70, sobrevenda=30):
    sup, inf, _ = bandas(df["close"], periodo_bb, desvios)
    r = rsi(df["close"], int(periodo_rsi))
    return [
        _c("Fecha abaixo da banda de Bollinger inferior", "Fecha acima da banda de Bollinger superior",
           df["close"] < inf, df["close"] > sup),
        _c(f"RSI abaixo de {sobrevenda}", f"RSI acima de {sobrecompra}", r < sobrevenda, r > sobrecompra),
    ]


def bollinger_rsi(df, periodo_bb=20, desvios=2.0, periodo_rsi=14, sobrecompra=70, sobrevenda=30):
    """Bollinger + RSI: CALL se fecha abaixo da banda inferior com RSI < sobrevenda;
    PUT se fecha acima da banda superior com RSI > sobrecompra."""
    return _de_condicoes(bollinger_rsi_condicoes(df, periodo_bb, desvios, periodo_rsi, sobrecompra, sobrevenda))


def pin_bar_condicoes(df, proporcao=2.5, corpo_max=0.3, exigir_extremo=1, n=20):
    corpo = (df["close"] - df["open"]).abs()
    amplitude = df["high"] - df["low"]
    pavio_sup = df["high"] - df[["open", "close"]].max(axis=1)
    pavio_inf = df[["open", "close"]].min(axis=1) - df["low"]
    base = (amplitude > 0) & (corpo <= corpo_max * amplitude)
    conds = [
        _c(f"Corpo pequeno (até {corpo_max:.0%} da vela)", None, base, base),
        _c(f"Pavio inferior longo (≥ {proporcao}× o corpo)", f"Pavio superior longo (≥ {proporcao}× o corpo)",
           (pavio_inf >= proporcao * corpo) & (pavio_sup * proporcao <= pavio_inf),
           (pavio_sup >= proporcao * corpo) & (pavio_inf * proporcao <= pavio_sup)),
    ]
    if int(exigir_extremo):
        conds.append(_c(f"Faz a mínima das últimas {int(n)} velas", f"Faz a máxima das últimas {int(n)} velas",
                        df["low"] <= df["low"].rolling(int(n)).min(),
                        df["high"] >= df["high"].rolling(int(n)).max()))
    return conds


def pin_bar(df, proporcao=2.5, corpo_max=0.3, exigir_extremo=1, n=20):
    """Pin Bar: pavio >= proporcao x corpo e corpo <= corpo_max do tamanho da vela.
    Pavio inferior longo = CALL, superior longo = PUT. exigir_extremo=1: a vela precisa
    fazer a mínima (CALL) / máxima (PUT) das últimas N velas."""
    return _de_condicoes(pin_bar_condicoes(df, proporcao, corpo_max, exigir_extremo, n))


def rompimento_sr_condicoes(df, n=20):
    resist, suporte = niveis_anteriores(df, n)
    return [_c(f"Fecha acima da máxima das {int(n)} velas anteriores",
               f"Fecha abaixo da mínima das {int(n)} velas anteriores",
               df["close"] > resist, df["close"] < suporte)]


def rompimento_sr(df, n=20):
    """Rompimento: CALL se fecha acima da máxima das N velas anteriores; PUT abaixo da mínima."""
    return _de_condicoes(rompimento_sr_condicoes(df, n))


def rejeicao_sr_condicoes(df, n=20):
    resist, suporte = niveis_anteriores(df, n)
    dentro = (df["close"] < resist) & (df["close"] > suporte)
    return [
        _c(f"Toca a mínima das {int(n)} velas anteriores", f"Toca a máxima das {int(n)} velas anteriores",
           df["low"] <= suporte, df["high"] >= resist),
        _c("Fecha de volta dentro da faixa", None, dentro, dentro),
    ]


def rejeicao_sr(df, n=20):
    """Rejeição: tocou a máxima/mínima das N velas anteriores e fechou de volta dentro
    do intervalo -> entra contra o rompimento (topo = PUT, fundo = CALL)."""
    return _de_condicoes(rejeicao_sr_condicoes(df, n))


def engolfo_condicoes(df):
    c = cor(df)
    c_ant = c.shift(1)
    o, f = df["open"], df["close"]
    o_ant, f_ant = o.shift(1), f.shift(1)
    maior = (f - o).abs() > (f_ant - o_ant).abs()
    return [
        _c("Vela anterior vermelha", "Vela anterior verde", c_ant == -1, c_ant == 1),
        _c("Vela atual verde", "Vela atual vermelha", c == 1, c == -1),
        _c("Corpo atual engole o corpo anterior", None,
           (o <= f_ant) & (f >= o_ant) & maior, (o >= f_ant) & (f <= o_ant) & maior),
    ]


def engolfo(df):
    """Engolfo: vela verde cujo corpo engole o corpo da vermelha anterior = CALL; inverso = PUT."""
    return _de_condicoes(engolfo_condicoes(df))


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #
def _resumo_doc(f) -> str:
    """Docstring em uma linha só."""
    return " ".join((f.__doc__ or "").split())


@dataclass
class Estrategia:
    """Estratégia registrada: função de sinal, condições nomeadas e grade de parâmetros."""

    nome: str
    sigla: str
    funcao: Callable
    parametros: dict = field(default_factory=dict)
    condicoes: Callable | None = None
    grade: dict = field(default_factory=dict)   # valores testados na otimização walk-forward

    @property
    def id(self) -> str:
        return self.funcao.__name__

    @property
    def descricao(self) -> str:
        return _resumo_doc(self.funcao)

    def gerar_sinais(self, df: pd.DataFrame, **params) -> pd.Series:
        return self.funcao(df, **{**self.parametros, **params})

    def gerar_condicoes(self, df: pd.DataFrame, **params) -> list[Condicao]:
        """Condições nomeadas. Sem `condicoes` registradas, o próprio sinal vira a condição única."""
        if self.condicoes is not None:
            return self.condicoes(df, **{**self.parametros, **params})
        s = self.gerar_sinais(df, **params)
        return [_c("Sinal da estratégia", None, s == "CALL", s == "PUT")]

    def combinacoes(self) -> list[dict]:
        """Todas as combinações da grade (sempre inclui os parâmetros padrão)."""
        if not self.grade:
            return [dict(self.parametros)]
        chaves = list(self.grade)
        combos = [{**self.parametros, **dict(zip(chaves, valores, strict=True))}
                  for valores in product(*(self.grade[k] for k in chaves))]
        if dict(self.parametros) not in combos:
            combos.insert(0, dict(self.parametros))
        return combos


ESTRATEGIAS = [
    Estrategia("Seguir cor", "COR", seguir_cor, condicoes=seguir_cor_condicoes),
    Estrategia("Reversão de sequência", "REV", reversao_sequencia, {"n": 3},
               condicoes=reversao_sequencia_condicoes, grade={"n": [2, 3, 4, 5]}),
    Estrategia("Cruzamento de médias", "MM", cruzamento_medias, {"rapida": 5, "lenta": 20},
               condicoes=cruzamento_medias_condicoes, grade={"rapida": [3, 5, 9], "lenta": [20, 50]}),
    Estrategia("RSI reversão", "RSI", rsi_reversao, {"periodo": 14, "sobrecompra": 70, "sobrevenda": 30},
               condicoes=rsi_reversao_condicoes,
               grade={"periodo": [7, 14, 21], "sobrecompra": [70, 80], "sobrevenda": [30, 20]}),
    Estrategia("MHI 1 (minoria)", "MHI", mhi, {"tamanho_quadrante": 5}, condicoes=mhi_condicoes),
    Estrategia("Tendência + recuo à média", "TEND", tendencia_recuo, {"periodo": 50},
               condicoes=tendencia_recuo_condicoes, grade={"periodo": [20, 50, 100]}),
    Estrategia("Bollinger + RSI", "BB", bollinger_rsi,
               {"periodo_bb": 20, "desvios": 2.0, "periodo_rsi": 14, "sobrecompra": 70, "sobrevenda": 30},
               condicoes=bollinger_rsi_condicoes, grade={"desvios": [2.0, 2.5], "periodo_rsi": [7, 14]}),
    Estrategia("Pin Bar", "PIN", pin_bar, {"proporcao": 2.5, "corpo_max": 0.3, "exigir_extremo": 1, "n": 20},
               condicoes=pin_bar_condicoes, grade={"proporcao": [2.0, 2.5, 3.0], "n": [10, 20]}),
    Estrategia("Rompimento S/R", "ROMP", rompimento_sr, {"n": 20}, condicoes=rompimento_sr_condicoes,
               grade={"n": [10, 20, 50]}),
    Estrategia("Rejeição S/R", "REJ", rejeicao_sr, {"n": 20}, condicoes=rejeicao_sr_condicoes,
               grade={"n": [10, 20, 50]}),
    Estrategia("Engolfo", "ENG", engolfo, condicoes=engolfo_condicoes),
]
POR_ID = {e.id: e for e in ESTRATEGIAS}

# Uma frase sem jargão, para a tela (a descrição técnica continua em `Estrategia.descricao`)
EXPLICACAO = {
    "seguir_cor": "Aposta que a próxima vela terá a mesma cor da última.",
    "reversao_sequencia": "Depois de várias velas seguidas da mesma cor, aposta na virada.",
    "cruzamento_medias": "Segue a direção quando o preço médio recente cruza o preço médio mais longo.",
    "rsi_reversao": "Aposta na volta do preço depois de uma subida ou queda exagerada.",
    "mhi": "A cada bloco de 5 velas, aposta na cor que apareceu menos nas últimas 3.",
    "tendencia_recuo": "Na tendência, espera o preço recuar até a média e voltar a andar a favor.",
    "bollinger_rsi": "Aposta na volta quando o preço sai muito da faixa normal e está esticado.",
    "pin_bar": "Procura velas com pavio longo, que mostram rejeição de um preço.",
    "rompimento_sr": "Segue o preço quando ele rompe a máxima ou a mínima recente.",
    "rejeicao_sr": "Aposta contra quando o preço toca a máxima ou mínima recente e volta.",
    "engolfo": "Segue a vela que 'engole' totalmente a vela anterior de cor oposta.",
}


def ultimo_valor(serie: pd.Series | None):
    """Último valor de uma Series de sinais ('CALL'/'PUT' ou None)."""
    if serie is None or serie.empty:
        return None
    v = serie.iloc[-1]
    return v if v in ("CALL", "PUT") else None
