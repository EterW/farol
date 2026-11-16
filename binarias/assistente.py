"""Assistente Farol: EXPLICA o que o Farol já calculou, em português simples. Não prevê preço, não gera sinal.

Opcional e desligado por padrão: só funciona com ANTHROPIC_API_KEY no arquivo .env (ou no ambiente).
A chave fica só no servidor local; o navegador nunca a vê.

Garantias (no prompt do sistema E conferidas aqui no código, em `validar`):
  * nunca diz que o preço "vai subir/descer", nunca recomenda entrar/sair, nunca promete resultado;
  * só cita números que vieram no JSON de entrada (ou na pergunta); estratégia ou ativo que não está no
    JSON = resposta descartada e substituída pelo texto padrão do Farol;
  * se não há vantagem comprovada, a explicação precisa dizer isso;
  * no máximo 5 linhas, e o aviso de que é informativa é SEMPRE acrescentado pelo código.

Custo: cache por (ativo, tempo gráfico, vela, pergunta), limite de chamadas por hora, tempo limite curto e
modelo configurável. Qualquer falha devolve o texto padrão: a tela nunca trava esperando a IA.
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

from .config import ADX_FORTE, ADX_MODERADO, BASE_DIR, CONFIANCA, MIN_OPS_AMOSTRA, PERIODO_ADX, PERIODO_ATR
from .estrategias import ESTRATEGIAS
from .log import obter

log = obter("assistente")

AVISO_FINAL = "Explicação informativa gerada por IA a partir dos números do Farol; não é recomendação de entrada."
AVISO_SEM_IA = "Texto informativo do Farol (sem IA); não é recomendação de entrada."
TEXTO_DESATIVADO = "Ative o assistente nas configurações (ANTHROPIC_API_KEY no arquivo .env)."
RECUSA = (
    "O assistente do Farol não diz se você deve entrar, sair, nem para onde o preço vai. "
    "Ele só explica o que o Farol calculou."
)
AVISO_PRIVACIDADE = (
    "Ao usar o assistente, os dados de mercado JÁ CALCULADOS pelo Farol (ativo, tendência, estado do veredito, "
    "probabilidade estimada com faixa e amostra, break-even) e a sua pergunta são enviados à API da Anthropic "
    "(serviço externo, pago por uso). Nenhum dado da sua banca ou do seu diário é enviado."
)
MAX_LINHAS = 5
MAX_PERGUNTA = 200
FORA_DO_TEMA = "FORA_DO_TEMA"

# Modelos que aceitam o parâmetro server-side `fallbacks` (beta): se o modelo principal recusar, outro continua.
_MODELOS_COM_FALLBACK = (
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-sonnet-5-5",
)
BETA_FALLBACK = "server-side-fallback-2026-07-01"

SISTEMA = f"""Você é o assistente do Farol, uma ferramenta de estudo estatístico de opções binárias.
Sua única função é EXPLICAR, em português simples do Brasil, o estado que o Farol já calculou e que vem no JSON
do usuário, e explicar termos (ADX, ATR, MACD, RSI, break-even, intervalo de confiança, walk-forward etc.).

Regras obrigatórias:
1. Nunca diga que o preço vai subir, descer, cair ou para onde vai. Você não prevê nada.
2. Nunca recomende entrar, sair, comprar, vender, nem diga que é uma boa hora. Nunca prometa resultado, lucro
   ou "assertividade".
3. Só use números que aparecem no JSON ou na pergunta. Não invente, não calcule números novos.
   Não cite estratégias nem ativos que não estão no JSON.
4. Se "sem_vantagem_comprovada" for true, diga com clareza: "sem vantagem comprovada".
5. No máximo {MAX_LINHAS} linhas curtas, texto corrido, sem títulos, sem listas longas, sem markdown.
6. Se a pergunta pedir recomendação, previsão, dica de entrada, ou fugir do tema do Farol/termos de mercado,
   responda exatamente: {FORA_DO_TEMA}
7. Não escreva aviso legal no final: o Farol acrescenta o aviso sozinho."""

# Expressões de previsão/recomendação/promessa que nunca podem aparecer (texto sem acento, minúsculo).
_PROIBIDAS = [
    r"\bvai (subir|descer|cair|baixar|valorizar|desvalorizar|disparar|despencar|reverter|virar)",
    r"\b(deve|devera|ira|tende a|promete) (subir|descer|cair|baixar|valorizar|disparar|despencar)",
    r"\b(recomend|aconselh)\w*",
    r"\bsugiro\b",
    r"\b(entre|entrar|saia|sair|compre|comprar|venda|vender|opere|operar) (agora|ja|nesta|neste|nessa|nesse)\b",
    r"\bpode (entrar|comprar|vender|operar)\b",
    r"\b(boa|otima|melhor) (hora|oportunidade|entrada)\b",
    r"\b(e|eh) hora de\b",
    r"\bgarant\w*",
    r"\bcom certeza\b",
    r"\bassertiv\w*",
    r"\blucro (certo|garantido|facil)\b",
    r"\bnao tem como perder\b",
]
_PERGUNTA_PROIBIDA = [
    r"\b(devo|posso|vale a pena|e bom|da para|da pra) (entrar|comprar|vender|operar|apostar)",
    r"\b(entro|compro|vendo|opero|aposto)\b",
    r"\bvai (subir|descer|cair|baixar)",
    r"\b(previsao|preve|prever|palpite|dica|sinal certo|qual entrada|que entrada)\b",
    r"\bquanto (vou|vai|posso) (ganhar|lucrar)",
    r"\b(call|put) ou (call|put)\b",
]
_MOEDAS = "EUR|USD|GBP|JPY|AUD|CHF|CAD|NZD|BTC|ETH|XAU|XAG|SEK|NOK|MXN|ZAR"
_PADRAO_ATIVO = re.compile(
    rf"\b(?:frx[A-Za-z]+|R_\d+|1HZ\d+V|(?:{_MOEDAS})\s?/?\s?(?:{_MOEDAS})|Volatility\s+\d+)", re.IGNORECASE
)
_NUMERO = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?")


# --------------------------------------------------------------------------- configuração (.env)
def carregar_env(caminho: str | None = None) -> dict[str, str]:
    """Lê KEY=valor do arquivo .env (sem sobrescrever o que já está no ambiente). Sem dependências."""
    caminho = caminho or os.path.join(BASE_DIR, ".env")
    lidos: dict[str, str] = {}
    try:
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, valor = linha.split("=", 1)
                chave, valor = chave.strip(), valor.strip().strip('"').strip("'")
                if chave and chave not in os.environ:
                    os.environ[chave] = valor
                lidos[chave] = valor
    except OSError:
        pass
    return lidos


@dataclass
class Configuracao:
    """Configuração do assistente (variáveis FAROL_ASSISTENTE_* no .env ou no ambiente)."""

    chave: str | None
    modelo: str = "claude-opus-5-5"
    limite_hora: int = 20
    tempo_limite: float = 20.0
    esforco: str = "low"

    @classmethod
    def do_ambiente(cls) -> Configuracao:
        carregar_env()

        def num(nome, padrao, tipo):
            try:
                return tipo(os.getenv(nome, padrao))
            except ValueError:
                return tipo(padrao)

        return cls(
            chave=os.getenv("ANTHROPIC_API_KEY") or None,
            modelo=os.getenv("FAROL_ASSISTENTE_MODELO", "claude-opus-5-5").strip() or "claude-opus-5-5",
            limite_hora=max(0, num("FAROL_ASSISTENTE_LIMITE_HORA", 20, int)),
            tempo_limite=min(60.0, max(3.0, num("FAROL_ASSISTENTE_TEMPO_LIMITE", 20.0, float))),
            esforco=os.getenv("FAROL_ASSISTENTE_ESFORCO", "low").strip() or "low",
        )

    @property
    def ativo(self) -> bool:
        return bool(self.chave)


# --------------------------------------------------------------------------- entrada: só dados já calculados
def _pct(v: float | None, casas: int = 1) -> float | None:
    return None if v is None else round(100 * float(v), casas)


def montar_dados(ativo: str, timeframe: str, ver: dict | None, humano: dict | None, ranking: dict | None) -> dict:
    """O JSON enviado à IA: SÓ números e textos que o Farol já calculou (nada de velas brutas)."""
    ver = ver or {}
    humano = humano or {}
    ranking = ranking or {}
    prob = ver.get("prob") or {}
    comprovada = bool(ver.get("comprovada"))
    dados: dict[str, Any] = {
        "ativo": ativo,
        "tempo_grafico": timeframe,
        "mercado": {
            "tendencia": humano.get("tendencia"),
            "forca": humano.get("forca"),
            "movimento": humano.get("movimento"),
            "resumo": humano.get("frase"),
        },
        "veredito": {
            "estado": ver.get("estado"),
            "titulo": ver.get("titulo"),
            "frase": ver.get("frase"),
            "estrategia_lider": ver.get("nome") if comprovada else None,
        },
        "sem_vantagem_comprovada": not comprovada,
        "break_even_pct": _pct(ranking.get("break_even") or ver.get("break_even"), 2),
        "payout_pct": _pct(ranking.get("payout"), 0),
        "minimo_operacoes": ranking.get("min_ops") or ver.get("min_ops"),
        "janela_velas": ranking.get("janela") or ver.get("janela"),
        "estrategias_testadas": ranking.get("testes"),
        "correcao_testes_multiplos": ranking.get("correcao"),
        # números de referência do próprio Farol (podem ser citados ao explicar termos)
        "referencias_do_farol": {
            "confianca_pct": round(100 * CONFIANCA),
            "adx_moderado": ADX_MODERADO,
            "adx_forte": ADX_FORTE,
            "periodo_adx": PERIODO_ADX,
            "periodo_atr": PERIODO_ATR,
            "rsi_sobrevenda": 30,
            "rsi_sobrecompra": 70,
            "minimo_operacoes_amostra": MIN_OPS_AMOSTRA,
        },
    }
    if comprovada and prob.get("ok"):
        dados["probabilidade_estimada"] = {
            "acerto_pct": _pct(prob.get("acerto")),
            "faixa_inferior_pct": _pct(prob.get("inf")),
            "faixa_superior_pct": _pct(prob.get("sup")),
            "operacoes": prob.get("n"),
        }
    return dados


# --------------------------------------------------------------------------- validação da resposta
def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _folhas(obj) -> list:
    if isinstance(obj, dict):
        return [x for v in obj.values() for x in _folhas(v)]
    if isinstance(obj, list | tuple):
        return [x for v in obj for x in _folhas(v)]
    return [obj]


def numeros_permitidos(dados: dict, pergunta: str = "") -> set[float]:
    """Todo número que aparece no JSON (valores e dentro de textos) ou na pergunta."""
    nums: set[float] = set()
    for v in [*_folhas(dados), pergunta]:
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, int | float):
            nums.add(float(v))
        elif isinstance(v, str):
            nums.update(float(m.replace(",", ".")) for m in _NUMERO.findall(v))
    return nums


def _numero_ok(texto: str, permitidos: set[float]) -> bool:
    casas = len(texto.split(",")[-1] if "," in texto else texto.split(".")[-1]) if re.search(r"[.,]", texto) else 0
    valor = float(texto.replace(",", "."))
    return any(abs(round(p, casas) - valor) < 1e-9 for p in permitidos)


def _ativos_do_json(dados: dict) -> set[str]:
    textos = " ".join(str(v) for v in _folhas(dados) if isinstance(v, str))
    return {re.sub(r"[\s/]|^frx", "", m, flags=re.IGNORECASE).upper() for m in _PADRAO_ATIVO.findall(textos)}


def validar(resposta: str, dados: dict, pergunta: str = "") -> tuple[bool, str]:
    """Confere a resposta da IA. Devolve (ok, motivo). Qualquer falha = descartar e usar o texto padrão."""
    if not resposta or not resposta.strip():
        return False, "resposta vazia"
    simples = _sem_acento(resposta)
    for padrao in _PROIBIDAS:
        if re.search(padrao, simples):
            return False, f"expressão proibida ({padrao})"
    permitidos = numeros_permitidos(dados, pergunta)
    for n in _NUMERO.findall(resposta):
        if not _numero_ok(n, permitidos):
            return False, f"número que não veio do Farol: {n}"
    citados_json = _sem_acento(" ".join(str(v) for v in _folhas(dados) if isinstance(v, str)) + " " + pergunta)
    for est in ESTRATEGIAS:
        nome = _sem_acento(est.nome)
        if nome in simples and nome not in citados_json:
            return False, f"estratégia fora do JSON: {est.nome}"
    no_json = _ativos_do_json(dados) | _ativos_do_json({"p": pergunta})
    for m in _PADRAO_ATIVO.findall(resposta):
        if re.sub(r"[\s/]|^frx", "", m, flags=re.IGNORECASE).upper() not in no_json:
            return False, f"ativo fora do JSON: {m}"
    if dados.get("sem_vantagem_comprovada") and "sem vantagem comprovada" not in simples:
        return False, "não disse que não há vantagem comprovada"
    return True, ""


def _limitar_linhas(texto: str) -> str:
    linhas = [linha.strip() for linha in texto.strip().splitlines() if linha.strip()]
    return "\n".join(linhas[:MAX_LINHAS])


def texto_padrao(dados: dict) -> str:
    """Explicação montada só com regras (sem IA): usada quando a IA está desligada, falha ou é descartada."""
    ver = dados.get("veredito") or {}
    partes = []
    resumo = (dados.get("mercado") or {}).get("resumo")
    if resumo:
        partes.append(resumo)
    if dados.get("sem_vantagem_comprovada"):
        partes.append(
            "Agora o Farol está sem vantagem comprovada: nenhuma estratégia passou nas regras estatísticas "
            "(mínimo de operações e margem de erro acima do break-even), por isso não há sinal de entrada."
        )
    elif ver.get("frase"):
        partes.append(f"Veredito do Farol: {ver.get('titulo') or ver.get('estado')}. {ver['frase']}")
    return " ".join(partes) or "O Farol ainda está calculando."


def recusa_padrao(dados: dict) -> str:
    """Recusa + o veredito atual do Farol (para perguntas como "devo entrar?")."""
    ver = dados.get("veredito") or {}
    estado = "sem vantagem comprovada" if dados.get("sem_vantagem_comprovada") else (ver.get("titulo") or "")
    return f"{RECUSA} Veredito do Farol agora: {estado}."


def pergunta_proibida(pergunta: str) -> bool:
    """Perguntas de recomendação/previsão são recusadas SEM chamar a IA (e sem custo)."""
    simples = _sem_acento(pergunta)
    return any(re.search(p, simples) for p in _PERGUNTA_PROIBIDA)


# --------------------------------------------------------------------------- serviço com cache e limite
@dataclass
class Assistente:
    """Chama a API com cache, limite por hora e tempo limite. `cliente` pode ser injetado (testes)."""

    config: Configuracao = field(default_factory=Configuracao.do_ambiente)
    cliente: Any = None
    cache_max: int = 200
    _cache: OrderedDict = field(default_factory=OrderedDict)
    _chamadas: deque = field(default_factory=deque)

    def status(self) -> dict:
        """Para a tela: ligado/desligado, modelo, limite e o aviso de privacidade."""
        return {
            "ativo": self.config.ativo,
            "modelo": self.config.modelo if self.config.ativo else None,
            "limite_hora": self.config.limite_hora,
            "restantes": self._restantes(),
            "texto_desativado": TEXTO_DESATIVADO,
            "privacidade": AVISO_PRIVACIDADE,
            "aviso": AVISO_FINAL,
            "max_pergunta": MAX_PERGUNTA,
        }

    def _restantes(self) -> int:
        agora = time.time()
        while self._chamadas and agora - self._chamadas[0] > 3600:
            self._chamadas.popleft()
        return max(0, self.config.limite_hora - len(self._chamadas))

    def _obter_cliente(self):
        if self.cliente is None:
            import anthropic  # só importa quando o assistente é usado (dependência opcional)

            self.cliente = anthropic.Anthropic(
                api_key=self.config.chave, timeout=self.config.tempo_limite, max_retries=1
            )
        return self.cliente

    def _chamar(self, dados: dict, pergunta: str) -> str:
        """Uma chamada à API. Devolve o texto (ou levanta exceção)."""
        conteudo = "Dados calculados pelo Farol (JSON):\n" + json.dumps(dados, ensure_ascii=False, sort_keys=True)
        conteudo += f"\n\nPergunta: {pergunta}" if pergunta else "\n\nExplique o estado atual em até 5 linhas."
        params: dict[str, Any] = {
            "model": self.config.modelo,
            "max_tokens": 2000,
            "system": SISTEMA,
            "messages": [{"role": "user", "content": conteudo}],
            "output_config": {"effort": self.config.esforco},
        }
        cliente = self._obter_cliente()
        if self.config.modelo in _MODELOS_COM_FALLBACK:
            resp = cliente.beta.messages.create(**params, betas=[BETA_FALLBACK], fallbacks="default")
        else:
            resp = cliente.messages.create(**params)
        if getattr(resp, "stop_reason", None) == "refusal":
            raise RuntimeError("a IA recusou responder")
        return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")

    def explicar(self, dados: dict, chave_vela: tuple, pergunta: str = "") -> dict:
        """Explicação curta. Sempre devolve um texto para a tela (da IA, validado, ou o padrão do Farol)."""
        pergunta = " ".join((pergunta or "").split())[:MAX_PERGUNTA]
        base = {"aviso": AVISO_SEM_IA, "pergunta": pergunta}
        if pergunta and pergunta_proibida(pergunta):
            return {**base, "fonte": "recusa", "texto": recusa_padrao(dados)}
        if not self.config.ativo:
            return {**base, "fonte": "desativado", "texto": texto_padrao(dados), "motivo": TEXTO_DESATIVADO}
        chave = (*chave_vela, _sem_acento(pergunta))
        if chave in self._cache:
            self._cache.move_to_end(chave)
            return {**self._cache[chave], "cache": True}
        if self._restantes() <= 0:
            return {
                **base,
                "fonte": "limite",
                "texto": texto_padrao(dados),
                "motivo": f"Limite de {self.config.limite_hora} chamadas por hora atingido.",
            }
        self._chamadas.append(time.time())
        try:
            bruto = self._chamar(dados, pergunta)
        except Exception as e:  # noqa: BLE001 - rede, chave inválida, limite da API, recusa: nunca trava a tela
            log.warning("Assistente: falha na chamada (%s: %s)", type(e).__name__, e)
            return {**base, "fonte": "erro", "texto": texto_padrao(dados), "motivo": "Assistente indisponível agora."}
        texto = _limitar_linhas(bruto)
        if texto.strip() == FORA_DO_TEMA or FORA_DO_TEMA in texto:
            saida = {**base, "fonte": "recusa", "texto": recusa_padrao(dados)}
        else:
            ok, motivo = validar(texto, dados, pergunta)
            if ok:
                saida = {**base, "fonte": "ia", "texto": texto, "aviso": AVISO_FINAL}
            else:
                log.warning("Assistente: resposta descartada (%s): %r", motivo, texto[:300])
                saida = {
                    **base,
                    "fonte": "descartada",
                    "texto": texto_padrao(dados),
                    "motivo": "A resposta da IA não passou na conferência do Farol e foi descartada.",
                }
        self._cache[chave] = saida
        while len(self._cache) > self.cache_max:
            self._cache.popitem(last=False)
        return saida
