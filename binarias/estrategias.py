"""Estratégias de entrada — o MESMO código é usado pelo backtest, pelo ranking, pela validação
e pelo modo ao vivo.

Cada estratégia recebe o DataFrame de velas FECHADAS e devolve uma Series alinhada ao df com
"CALL", "PUT" ou None. Um sinal na vela i significa: entrar na ABERTURA da vela i+1.
Regra de ouro: o valor na vela i só pode depender das velas 0..i (há um teste automático
que verifica isso truncando o futuro).

A função de PREPARO tem a mesma assinatura. Um valor na vela i significa: "depois do fechamento
da vela i a condição está quase completa — a próxima vela pode disparar nessa direção".

Para criar a sua: escreva as funções (df, **params) -> Series e registre em ESTRATEGIAS.
"""
from dataclasses import dataclass, field
from itertools import product
from typing import Callable

import pandas as pd

from .indicadores import atr, bandas, cor, niveis_anteriores, rsi, sma


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


def _nada(df: pd.DataFrame) -> pd.Series:
    return pd.Series(None, index=df.index, dtype=object)


def _granularidade(df: pd.DataFrame) -> int:
    d = df["epoch"].diff()
    d = d[d > 0]
    return int(d.mode().iloc[0]) if len(d) else 60


def _posicao_quadrante(df, tamanho_quadrante):
    gran = _granularidade(df)
    return (df["epoch"] // gran) % int(tamanho_quadrante), gran


# --------------------------------------------------------------------------- #
# Estratégias (sinal + preparo)
# --------------------------------------------------------------------------- #
def seguir_cor(df):
    """Entra na mesma cor da última vela."""
    c = cor(df)
    return _sinais(c == 1, c == -1)


def seguir_cor_prep(df):
    """Sempre há uma direção armada: a cor da última vela fechada."""
    return seguir_cor(df)


def reversao_sequencia(df, n=3):
    """Após N velas seguidas da mesma cor, entra contra a sequência."""
    n = int(n)
    c = cor(df)
    todas_verdes = (c == 1).astype(int).rolling(n).sum() == n
    todas_vermelhas = (c == -1).astype(int).rolling(n).sum() == n
    return _sinais(todas_vermelhas, todas_verdes)


def reversao_sequencia_prep(df, n=3):
    """Já há N-1 velas seguidas da mesma cor: mais uma completa a sequência."""
    k = int(n) - 1
    if k <= 0:
        return _nada(df)
    return reversao_sequencia(df, k)


def cruzamento_medias(df, rapida=5, lenta=20):
    """CALL quando a média rápida cruza a lenta para cima; PUT para baixo."""
    mr, ml = sma(df["close"], rapida), sma(df["close"], lenta)
    validas = mr.notna() & ml.notna()
    validas_ant = validas.shift(1, fill_value=False)
    acima = mr > ml
    abaixo = mr < ml
    acima_ant = acima.shift(1, fill_value=False)
    abaixo_ant = abaixo.shift(1, fill_value=False)
    base = validas & validas_ant
    return _sinais(base & acima & ~acima_ant, base & abaixo & ~abaixo_ant)


def cruzamento_medias_prep(df, rapida=5, lenta=20):
    """Médias convergindo e a menos de 0,3 ATR uma da outra."""
    gap = sma(df["close"], rapida) - sma(df["close"], lenta)
    perto = (gap.abs() < gap.shift(1).abs()) & (gap.abs() <= 0.3 * atr(df))
    return _sinais(perto & (gap < 0), perto & (gap > 0))


def rsi_reversao(df, periodo=14, sobrecompra=70, sobrevenda=30):
    """RSI (Wilder): CALL ao sair da sobrevenda, PUT ao sair da sobrecompra."""
    r = rsi(df["close"], int(periodo))
    ant = r.shift(1)
    return _sinais((ant < sobrevenda) & (r >= sobrevenda), (ant > sobrecompra) & (r <= sobrecompra))


def rsi_reversao_prep(df, periodo=14, sobrecompra=70, sobrevenda=30):
    """RSI dentro da sobrevenda (espera sair = CALL) ou da sobrecompra (PUT)."""
    r = rsi(df["close"], int(periodo))
    return _sinais(r < sobrevenda, r > sobrecompra)


def mhi(df, tamanho_quadrante=5):
    """MHI 1 (minoria): no fim de cada quadrante de 5 velas (alinhado ao horário), olha as 3
    últimas velas e entra na cor da MINORIA na 1ª vela do próximo quadrante. Se houver doji
    entre as 3, ou se faltar vela no meio (buraco de mercado), não entra."""
    if len(df) < 3:
        return _nada(df)
    tamanho_quadrante = int(tamanho_quadrante)
    posicao, gran = _posicao_quadrante(df, tamanho_quadrante)
    c = cor(df)
    soma3 = c.rolling(3).sum()
    tem_doji = (c == 0).astype(int).rolling(3).sum() > 0
    continuas = (df["epoch"] - df["epoch"].shift(2)) == 2 * gran
    fim_quadrante = (posicao == tamanho_quadrante - 1) & ~tem_doji & continuas
    # maioria verde (soma > 0) -> minoria vermelha -> PUT
    return _sinais(fim_quadrante & (soma3 < 0), fim_quadrante & (soma3 > 0))


def mhi_prep(df, tamanho_quadrante=5):
    """Penúltima vela do quadrante: as 2 primeiras das 3 analisadas já têm a mesma cor,
    então a maioria (e a direção) já está definida."""
    if len(df) < 2:
        return _nada(df)
    tamanho_quadrante = int(tamanho_quadrante)
    posicao, gran = _posicao_quadrante(df, tamanho_quadrante)
    c = cor(df)
    continuas = (df["epoch"] - df["epoch"].shift(1)) == gran
    armado = (posicao == tamanho_quadrante - 2) & (c == c.shift(1)) & (c != 0) & continuas
    return _sinais(armado & (c == -1), armado & (c == 1))


def tendencia_recuo(df, periodo=50):
    """Tendência + recuo: CALL se fecha acima da média, a vela anterior tocou/cruzou a média
    e a atual fecha verde (voltou a subir). PUT no inverso."""
    ma = sma(df["close"], periodo)
    ma_ant = ma.shift(1)
    c = cor(df)
    call = (df["close"] > ma) & (df["low"].shift(1) <= ma_ant) & (c == 1)
    put = (df["close"] < ma) & (df["high"].shift(1) >= ma_ant) & (c == -1)
    return _sinais(call, put)


def tendencia_recuo_prep(df, periodo=50):
    """Preço do lado da tendência e recuando até a média (tocou ou a menos de 0,3 ATR)."""
    ma = sma(df["close"], periodo)
    folga = 0.3 * atr(df)
    call = (df["close"] > ma) & (df["low"] <= ma + folga)
    put = (df["close"] < ma) & (df["high"] >= ma - folga)
    return _sinais(call, put)


def bollinger_rsi(df, periodo_bb=20, desvios=2.0, periodo_rsi=14, sobrecompra=70, sobrevenda=30):
    """Bollinger + RSI: CALL se fecha abaixo da banda inferior com RSI < sobrevenda;
    PUT se fecha acima da banda superior com RSI > sobrecompra."""
    sup, inf, _ = bandas(df["close"], periodo_bb, desvios)
    r = rsi(df["close"], int(periodo_rsi))
    return _sinais((df["close"] < inf) & (r < sobrevenda), (df["close"] > sup) & (r > sobrecompra))


def bollinger_rsi_prep(df, periodo_bb=20, desvios=2.0, periodo_rsi=14, sobrecompra=70, sobrevenda=30):
    """Fechamento colado na banda (a menos de 0,25 desvio) e RSI a até 5 pontos do extremo."""
    sup, inf, dp = bandas(df["close"], periodo_bb, desvios)
    r = rsi(df["close"], int(periodo_rsi))
    call = (df["close"] < inf + 0.25 * dp) & (r < sobrevenda + 5)
    put = (df["close"] > sup - 0.25 * dp) & (r > sobrecompra - 5)
    return _sinais(call, put)


def pin_bar(df, proporcao=2.5, corpo_max=0.3, exigir_extremo=1, n=20):
    """Pin Bar: pavio >= proporcao x corpo e corpo <= corpo_max do tamanho da vela.
    Pavio inferior longo = CALL, superior longo = PUT. exigir_extremo=1: a vela precisa
    fazer a mínima (CALL) / máxima (PUT) das últimas N velas."""
    corpo = (df["close"] - df["open"]).abs()
    amplitude = df["high"] - df["low"]
    pavio_sup = df["high"] - df[["open", "close"]].max(axis=1)
    pavio_inf = df[["open", "close"]].min(axis=1) - df["low"]
    base = (amplitude > 0) & (corpo <= corpo_max * amplitude)
    call = base & (pavio_inf >= proporcao * corpo) & (pavio_sup * proporcao <= pavio_inf)
    put = base & (pavio_sup >= proporcao * corpo) & (pavio_inf * proporcao <= pavio_sup)
    if int(exigir_extremo):
        call &= df["low"] <= df["low"].rolling(int(n)).min()
        put &= df["high"] >= df["high"].rolling(int(n)).max()
    return _sinais(call, put)


def pin_bar_prep(df, proporcao=2.5, corpo_max=0.3, exigir_extremo=1, n=20):
    """Com exigir_extremo=1: preço testando a mínima/máxima das últimas N velas (a menos de
    0,25 ATR), onde uma rejeição viraria pin bar. Sem extremo: pin bar "quase" formado."""
    if not int(exigir_extremo):
        return pin_bar(df, proporcao * 0.6, min(1.0, corpo_max * 1.5), 0, n)
    folga = 0.25 * atr(df)
    call = df["low"] <= df["low"].rolling(int(n)).min() + folga
    put = df["high"] >= df["high"].rolling(int(n)).max() - folga
    return _sinais(call, put)


def rompimento_sr(df, n=20):
    """Rompimento: CALL se fecha acima da máxima das N velas anteriores; PUT abaixo da mínima."""
    resist, suporte = niveis_anteriores(df, n)
    return _sinais(df["close"] > resist, df["close"] < suporte)


def _perto_dos_niveis(df, n):
    """Fechamento a menos de 0,25 ATR da máxima/mínima que valerá para a PRÓXIMA vela."""
    folga = 0.25 * atr(df)
    resist = df["high"].rolling(int(n)).max()
    suporte = df["low"].rolling(int(n)).min()
    return df["close"] >= resist - folga, df["close"] <= suporte + folga


def rompimento_sr_prep(df, n=20):
    """Fechamento encostado na resistência (CALL) ou no suporte (PUT)."""
    perto_topo, perto_fundo = _perto_dos_niveis(df, n)
    return _sinais(perto_topo, perto_fundo)


def rejeicao_sr(df, n=20):
    """Rejeição: tocou a máxima/mínima das N velas anteriores e fechou de volta dentro
    do intervalo -> entra contra o rompimento (topo = PUT, fundo = CALL)."""
    resist, suporte = niveis_anteriores(df, n)
    dentro = (df["close"] < resist) & (df["close"] > suporte)
    return _sinais(dentro & (df["low"] <= suporte), dentro & (df["high"] >= resist))


def rejeicao_sr_prep(df, n=20):
    """Fechamento encostado na resistência (PUT se rejeitar) ou no suporte (CALL)."""
    perto_topo, perto_fundo = _perto_dos_niveis(df, n)
    return _sinais(perto_fundo, perto_topo)


def engolfo(df):
    """Engolfo: vela verde cujo corpo engole o corpo da vermelha anterior = CALL; inverso = PUT."""
    c = cor(df)
    c_ant = c.shift(1)
    o, f = df["open"], df["close"]
    o_ant, f_ant = o.shift(1), f.shift(1)
    maior = (f - o).abs() > (f_ant - o_ant).abs()
    alta = (c == 1) & (c_ant == -1) & (o <= f_ant) & (f >= o_ant) & maior
    baixa = (c == -1) & (c_ant == 1) & (o >= f_ant) & (f <= o_ant) & maior
    return _sinais(alta, baixa)


def engolfo_prep(df):
    """Vela vermelha (verde) de corpo até 1 ATR depois de 3 velas de queda (alta):
    uma vela contrária maior a engoliria."""
    c = cor(df)
    corpo_ok = (df["close"] - df["open"]).abs() <= atr(df)
    queda = df["close"] < df["close"].shift(3)
    alta = df["close"] > df["close"].shift(3)
    return _sinais((c == -1) & corpo_ok & queda, (c == 1) & corpo_ok & alta)


# --------------------------------------------------------------------------- #
def _resumo_doc(f) -> str:
    """Docstring em uma linha só."""
    return " ".join((f.__doc__ or "").split())


@dataclass
class Estrategia:
    nome: str
    sigla: str
    funcao: Callable
    parametros: dict = field(default_factory=dict)
    preparo: Callable | None = None
    grade: dict = field(default_factory=dict)   # valores testados na otimização walk-forward

    @property
    def id(self) -> str:
        return self.funcao.__name__

    @property
    def descricao(self) -> str:
        return _resumo_doc(self.funcao)

    def gerar_sinais(self, df: pd.DataFrame, **params) -> pd.Series:
        return self.funcao(df, **{**self.parametros, **params})

    def gerar_preparo(self, df: pd.DataFrame, **params) -> pd.Series:
        if self.preparo is None:
            return _nada(df)
        return self.preparo(df, **{**self.parametros, **params})

    def combinacoes(self) -> list[dict]:
        """Todas as combinações da grade (sempre inclui os parâmetros padrão)."""
        if not self.grade:
            return [dict(self.parametros)]
        chaves = list(self.grade)
        combos = [{**self.parametros, **dict(zip(chaves, valores))}
                  for valores in product(*(self.grade[k] for k in chaves))]
        if dict(self.parametros) not in combos:
            combos.insert(0, dict(self.parametros))
        return combos


ESTRATEGIAS = [
    Estrategia("Seguir cor", "COR", seguir_cor, preparo=seguir_cor_prep),
    Estrategia("Reversão de sequência", "REV", reversao_sequencia, {"n": 3},
               preparo=reversao_sequencia_prep, grade={"n": [2, 3, 4, 5]}),
    Estrategia("Cruzamento de médias", "MM", cruzamento_medias, {"rapida": 5, "lenta": 20},
               preparo=cruzamento_medias_prep, grade={"rapida": [3, 5, 9], "lenta": [20, 50]}),
    Estrategia("RSI reversão", "RSI", rsi_reversao, {"periodo": 14, "sobrecompra": 70, "sobrevenda": 30},
               preparo=rsi_reversao_prep,
               grade={"periodo": [7, 14, 21], "sobrecompra": [70, 80], "sobrevenda": [30, 20]}),
    Estrategia("MHI 1 (minoria)", "MHI", mhi, {"tamanho_quadrante": 5}, preparo=mhi_prep),
    Estrategia("Tendência + recuo à média", "TEND", tendencia_recuo, {"periodo": 50},
               preparo=tendencia_recuo_prep, grade={"periodo": [20, 50, 100]}),
    Estrategia("Bollinger + RSI", "BB", bollinger_rsi,
               {"periodo_bb": 20, "desvios": 2.0, "periodo_rsi": 14, "sobrecompra": 70, "sobrevenda": 30},
               preparo=bollinger_rsi_prep, grade={"desvios": [2.0, 2.5], "periodo_rsi": [7, 14]}),
    Estrategia("Pin Bar", "PIN", pin_bar, {"proporcao": 2.5, "corpo_max": 0.3, "exigir_extremo": 1, "n": 20},
               preparo=pin_bar_prep, grade={"proporcao": [2.0, 2.5, 3.0], "n": [10, 20]}),
    Estrategia("Rompimento S/R", "ROMP", rompimento_sr, {"n": 20}, preparo=rompimento_sr_prep,
               grade={"n": [10, 20, 50]}),
    Estrategia("Rejeição S/R", "REJ", rejeicao_sr, {"n": 20}, preparo=rejeicao_sr_prep,
               grade={"n": [10, 20, 50]}),
    Estrategia("Engolfo", "ENG", engolfo, preparo=engolfo_prep),
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
