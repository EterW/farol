"""Assistente Farol: EXPLICA o que o Farol já calculou, em português simples. Não prevê preço, não gera sinal.

Opcional e desligado por padrão. Provedor escolhido no .env (ASSISTENTE_PROVEDOR):
  * desligado (padrão): o botão mostra a explicação automática do Farol, sem IA;
  * ollama: modelo local no servidor Ollama (http://127.0.0.1:11434), nada sai do computador;
  * anthropic: API da Anthropic (precisa de ANTHROPIC_API_KEY; a chave fica só no servidor local).
As MESMAS regras de segurança e a MESMA validação da resposta valem para qualquer provedor.

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

import contextlib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

from .config import ADX_FORTE, ADX_MODERADO, BASE_DIR, CONFIANCA, MIN_OPS_AMOSTRA, PERIODO_ADX, PERIODO_ATR
from .estrategias import ESTRATEGIAS
from .log import obter

log = obter("assistente")

AVISO_FINAL = "Explicação informativa gerada por IA a partir dos números do Farol; não é recomendação de entrada."
AVISO_SEM_IA = "Texto informativo do Farol (sem IA); não é recomendação de entrada."
TEXTO_DESATIVADO = (
    "Ative o assistente nas configurações: no arquivo .env, use ASSISTENTE_PROVEDOR=ollama (modelo local, grátis) "
    "ou ASSISTENTE_PROVEDOR=anthropic (com ANTHROPIC_API_KEY) e reinicie o Farol."
)
PROVEDORES = ("desligado", "ollama", "anthropic")
MODELO_PADRAO = {"anthropic": "claude-opus-5-5", "ollama": "llama3.2"}
TEMPO_PADRAO = {"anthropic": 20.0, "ollama": 60.0}
LIMITE_HORA_PADRAO = {"anthropic": 20, "ollama": 60}
OLLAMA_URL_PADRAO = "http://127.0.0.1:11434"
INSTALAR_OLLAMA = "winget install Ollama.Ollama (ou baixe em https://ollama.com/download)"
RECUSA = (
    "O assistente do Farol não diz se você deve entrar, sair, nem para onde o preço vai. "
    "Ele só explica o que o Farol calculou."
)
AVISO_PRIVACIDADE = (
    "Ao usar o assistente, os dados de mercado JÁ CALCULADOS pelo Farol (ativo, tendência, estado do veredito, "
    "probabilidade estimada com faixa e amostra, break-even) e a sua pergunta são enviados à API da Anthropic "
    "(serviço externo, pago por uso). Nenhum dado da sua banca ou do seu diário é enviado."
)
AVISO_PRIVACIDADE_LOCAL = (
    "Assistente local (Ollama neste computador): os números calculados e a sua pergunta não saem da sua máquina. "
    "Dados da banca e do diário nunca são enviados."
)
AVISO_PRIVACIDADE_DESLIGADO = (
    "Assistente desligado: nada é enviado a lugar nenhum. Com o Ollama, tudo roda no seu computador; com a "
    "Anthropic, os números calculados e a pergunta vão para um serviço externo."
)


class ErroProvedor(Exception):
    """Falha do provedor com uma mensagem clara para a tela (ex.: Ollama parado, modelo não instalado)."""


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
    """Configuração do assistente (variáveis ASSISTENTE_* no .env ou no ambiente; FAROL_ASSISTENTE_* ainda valem)."""

    provedor: str = "desligado"
    chave: str | None = None
    modelo: str = ""
    limite_hora: int = 0
    tempo_limite: float = 0.0
    esforco: str = "low"
    ollama_url: str = OLLAMA_URL_PADRAO

    def __post_init__(self):
        self.provedor = (self.provedor or "desligado").strip().lower()
        if self.provedor not in PROVEDORES:
            log.warning("ASSISTENTE_PROVEDOR inválido (%r): assistente desligado", self.provedor)
            self.provedor = "desligado"
        self.modelo = self.modelo or MODELO_PADRAO.get(self.provedor, "")
        self.tempo_limite = self.tempo_limite or TEMPO_PADRAO.get(self.provedor, 20.0)
        self.limite_hora = self.limite_hora or LIMITE_HORA_PADRAO.get(self.provedor, 20)
        self.ollama_url = (self.ollama_url or OLLAMA_URL_PADRAO).rstrip("/")

    @classmethod
    def do_ambiente(cls) -> Configuracao:
        carregar_env()

        def var(*nomes: str) -> str:
            return next((os.environ[n].strip() for n in nomes if os.environ.get(n, "").strip()), "")

        def num(tipo, padrao, *nomes):
            try:
                return tipo(var(*nomes) or padrao)
            except ValueError:
                return tipo(padrao)

        provedor = var("ASSISTENTE_PROVEDOR") or "desligado"
        modelo = var("ASSISTENTE_MODELO") or (var("FAROL_ASSISTENTE_MODELO") if provedor == "anthropic" else "")
        return cls(
            provedor=provedor,
            chave=os.getenv("ANTHROPIC_API_KEY") or None,
            modelo=modelo,
            limite_hora=max(0, num(int, 0, "ASSISTENTE_LIMITE_HORA", "FAROL_ASSISTENTE_LIMITE_HORA")),
            tempo_limite=min(
                120.0, max(0.0, num(float, 0, "ASSISTENTE_TEMPO_LIMITE", "FAROL_ASSISTENTE_TEMPO_LIMITE"))
            ),
            esforco=var("ASSISTENTE_ESFORCO", "FAROL_ASSISTENTE_ESFORCO") or "low",
            ollama_url=var("ASSISTENTE_OLLAMA_URL") or OLLAMA_URL_PADRAO,
        )

    @property
    def ativo(self) -> bool:
        return self.provedor == "ollama" or (self.provedor == "anthropic" and bool(self.chave))

    @property
    def local(self) -> bool:
        """Ollama em 127.0.0.1/localhost = nada sai do computador."""
        host = urllib.parse.urlparse(self.ollama_url).hostname or ""
        return self.provedor == "ollama" and host in ("127.0.0.1", "localhost", "::1")

    @property
    def motivo_desligado(self) -> str:
        if self.provedor == "anthropic" and not self.chave:
            return "ASSISTENTE_PROVEDOR=anthropic, mas falta ANTHROPIC_API_KEY no arquivo .env. Preencha e reinicie."
        return TEXTO_DESATIVADO

    @property
    def privacidade(self) -> str:
        if not self.ativo:
            return AVISO_PRIVACIDADE_DESLIGADO
        if self.provedor == "ollama":
            return (
                AVISO_PRIVACIDADE_LOCAL
                if self.local
                else (
                    f"Os números calculados pelo Farol e a sua pergunta vão para o servidor Ollama em {self.ollama_url}"
                    " (fora deste computador). Banca e diário nunca são enviados."
                )
            )
        return AVISO_PRIVACIDADE


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
    """Chama o provedor com cache, limite por hora e tempo limite. `cliente` (Anthropic) pode ser injetado."""

    config: Configuracao = field(default_factory=Configuracao.do_ambiente)
    cliente: Any = None
    cache_max: int = 200
    _cache: OrderedDict = field(default_factory=OrderedDict)
    _chamadas: deque = field(default_factory=deque)

    def status(self) -> dict:
        """Para a tela: ligado/desligado, modelo, limite e o aviso de privacidade."""
        c = self.config
        return {
            "ativo": c.ativo,
            "provedor": c.provedor,
            "local": c.local,
            "modelo": c.modelo if c.ativo else None,
            "limite_hora": c.limite_hora,
            "restantes": self._restantes(),
            "tempo_limite": c.tempo_limite,
            "texto_desativado": c.motivo_desligado,
            "privacidade": c.privacidade,
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
            try:
                import anthropic  # só importa quando o assistente é usado (dependência opcional)
            except ImportError:
                raise ErroProvedor('SDK da Anthropic não instalado. Rode: pip install -e ".[assistente]"') from None
            self.cliente = anthropic.Anthropic(
                api_key=self.config.chave, timeout=self.config.tempo_limite, max_retries=1
            )
        return self.cliente

    @staticmethod
    def _conteudo(dados: dict, pergunta: str) -> str:
        conteudo = "Dados calculados pelo Farol (JSON):\n" + json.dumps(dados, ensure_ascii=False, sort_keys=True)
        return conteudo + (f"\n\nPergunta: {pergunta}" if pergunta else "\n\nExplique o estado atual em até 5 linhas.")

    def _chamar(self, dados: dict, pergunta: str) -> str:
        """Uma chamada ao provedor configurado. Devolve o texto (ou levanta exceção)."""
        conteudo = self._conteudo(dados, pergunta)
        if self.config.provedor == "ollama":
            return self._chamar_ollama(conteudo)
        return self._chamar_anthropic(conteudo)

    def _chamar_anthropic(self, conteudo: str) -> str:
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

    def _chamar_ollama(self, conteudo: str) -> str:
        """POST /api/chat no servidor Ollama (sem streaming). Erros viram ErroProvedor com o comando de solução."""
        c = self.config
        corpo = json.dumps(
            {
                "model": c.modelo,
                "messages": [{"role": "system", "content": SISTEMA}, {"role": "user", "content": conteudo}],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 400},
            }
        ).encode("utf-8")
        pedido = urllib.request.Request(
            f"{c.ollama_url}/api/chat", data=corpo, headers={"Content-Type": "application/json"}, method="POST"
        )
        abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # servidor local: nunca via proxy
        parado = (
            f"O Ollama não está rodando em {c.ollama_url}. Instale com: {INSTALAR_OLLAMA}; "
            f"depois rode: ollama pull {c.modelo} (e, se precisar, ollama serve)."
        )
        try:
            with abridor.open(pedido, timeout=c.tempo_limite) as r:
                resposta = json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            detalhe = ""
            with contextlib.suppress(ValueError, OSError, AttributeError):
                detalhe = str(json.loads(e.read().decode("utf-8", "replace")).get("error", ""))
            if e.code == 404 or "not found" in detalhe.lower():
                raise ErroProvedor(
                    f"O modelo “{c.modelo}” não está instalado no Ollama. Baixe com: ollama pull {c.modelo}"
                ) from None
            raise ErroProvedor(f"O Ollama respondeu com erro {e.code}: {detalhe[:150] or e.reason}") from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                raise ErroProvedor(self._msg_demora()) from None
            raise ErroProvedor(parado) from None
        except TimeoutError:
            raise ErroProvedor(self._msg_demora()) from None
        except ConnectionError:
            raise ErroProvedor(parado) from None
        except ValueError:
            raise ErroProvedor("O Ollama devolveu uma resposta que não é JSON.") from None
        if not isinstance(resposta, dict):
            raise ErroProvedor("O Ollama devolveu uma resposta inesperada.")
        if resposta.get("error"):
            raise ErroProvedor(f"O Ollama respondeu com erro: {str(resposta['error'])[:150]}")
        texto = str((resposta.get("message") or {}).get("content") or "")
        return re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL).strip()  # modelos que "pensam alto"

    def _msg_demora(self) -> str:
        return (
            f"O Ollama não respondeu em {self.config.tempo_limite:g} s. Na primeira vez o modelo demora para carregar; "
            "tente de novo ou use um modelo menor (ASSISTENTE_MODELO)."
        )

    def explicar(self, dados: dict, chave_vela: tuple, pergunta: str = "") -> dict:
        """Explicação curta. Sempre devolve um texto para a tela (da IA, validado, ou o padrão do Farol)."""
        pergunta = " ".join((pergunta or "").split())[:MAX_PERGUNTA]
        base = {"aviso": AVISO_SEM_IA, "pergunta": pergunta}
        if pergunta and pergunta_proibida(pergunta):
            return {**base, "fonte": "recusa", "texto": recusa_padrao(dados)}
        if not self.config.ativo:
            motivo = self.config.motivo_desligado
            return {**base, "fonte": "desativado", "texto": texto_padrao(dados), "motivo": motivo}
        chave = (self.config.provedor, self.config.modelo, *chave_vela, _sem_acento(pergunta))
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
        except ErroProvedor as e:
            log.warning("Assistente (%s): %s", self.config.provedor, e)
            return {**base, "fonte": "erro", "texto": texto_padrao(dados), "motivo": str(e)}
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
