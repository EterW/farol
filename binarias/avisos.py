"""Estratégia líder (com histerese) e avisos do Farol (som + notificação), decididos no SERVIDOR.

Só a LÍDER gera aviso sonoro e notificação, em 3 momentos:
  1. FORMANDO   progresso de formação passou do limite (uma vez por vela, nunca na vela da entrada);
  2. ENTRAR     a líder deu sinal na vela que fechou e não há conflito (som diferente p/ compra e venda);
  3. RESULTADO  a operação da líder expirou: WIN/LOSS/EMPATE + placar da sessão.
CONFLITO aparece na tela, sem som e sem notificação. Troca de líder: aviso discreto, sem som.
Sem estratégia comprovada: nenhum aviso de formação ou de entrada. Exceção opcional e DESLIGADA por
padrão: "avisar também candidatas não comprovadas", com título e som próprios ("OBSERVAÇÃO").
"""

from dataclasses import dataclass, field

from .config import LIDER_MARGEM_IC, LIDER_VELAS_CONFIRMACAO, PROGRESSO_LIMITE
from .veredito import ACAO, SETA, comprovada

MARCA = "Farol"


def nome_ativo(simbolo: str | None) -> str:
    """frxEURUSD -> EUR/USD (outros símbolos ficam como estão)."""
    s = (simbolo or "").removeprefix("frx")
    return f"{s[:3]}/{s[3:]}" if len(s) == 6 and s.isalpha() and s.isupper() else s


def _velas(n: int) -> str:
    return f"{n} vela{'s' if n != 1 else ''}"


def _pct(v: float) -> str:
    return f"{100 * v:.0f}%"


def aviso(
    categoria: str,
    titulo: str,
    texto: str,
    som: str | None = None,
    notificar: bool = False,
    direcao: str | None = None,
    vela: int | None = None,
) -> dict:
    """Formato único de aviso enviado ao navegador (que só toca o som e mostra o que vier aqui)."""
    return {
        "categoria": categoria,
        "titulo": titulo,
        "texto": texto,
        "som": som,
        "notificar": notificar,
        "dir": direcao,
        "vela": vela,
    }


# --------------------------------------------------------------------------- textos (um lugar só)
def texto_formando(nome: str, ativo: str, direcao: str | None, pct: int) -> dict:
    """Texto do aviso FORMANDO (preparo)."""
    lado = f" ({ACAO[direcao]} {SETA[direcao]}, {pct}%)" if direcao else f" ({pct}%)"
    return {
        "titulo": f"{MARCA} · se formando",
        "texto": f"{MARCA}: {nome} está se formando em {ativo}{lado}. Fique atento: o sinal pode sair na próxima vela.",
    }


def texto_entrada(direcao: str, ativo: str, expiracao: int, prob: dict | None) -> dict:
    """Texto do aviso ENTRAR AGORA, com probabilidade, faixa e amostra."""
    texto = f"Entre AGORA: {ACAO[direcao]} {SETA[direcao]} em {ativo}, expiração {_velas(expiracao)}."
    if prob and prob.get("ok"):
        texto += (
            f" Probabilidade estimada {_pct(prob['acerto'])} (entre {_pct(prob['inf'])} e "
            f"{_pct(prob['sup'])}, {prob['n']} operações)."
        )
    return {"titulo": f"{MARCA} · ENTRE AGORA: {ACAO[direcao]} {SETA[direcao]}", "texto": texto}


def texto_resultado(resultado: str, nome: str, ativo: str, placar: dict) -> dict:
    """Texto do aviso de RESULTADO, com o placar da sessão."""
    rotulo = {"WIN": "WIN (acerto)", "LOSS": "LOSS (erro)", "EMPATE": "EMPATE"}.get(resultado, resultado)
    return {
        "titulo": f"{MARCA} · {resultado}",
        "texto": f"{nome} em {ativo}: {rotulo}. Placar da sessão: {placar['WIN']} WIN · "
        f"{placar['LOSS']} LOSS · {placar['EMPATE']} EMPATE.",
    }


def texto_observacao(nome: str, ativo: str, direcao: str | None, quando: str) -> dict:
    """Texto do aviso de candidata NÃO comprovada (só observação)."""
    lado = f"{ACAO[direcao]} {SETA[direcao]}" if direcao else ""
    if quando == "formando":
        acao = f"está se formando em {ativo}" + (f" ({lado})" if lado else "")
    else:
        acao = f"indicaria {lado} agora em {ativo}"
    return {
        "titulo": f"{MARCA} · OBSERVAÇÃO (não comprovada)",
        "texto": f"OBSERVAÇÃO, sem vantagem comprovada: {nome} {acao}. Não é recomendação.",
    }


def exemplos() -> list[dict]:
    """Os 3 tipos de aviso, com os textos reais, para o botão "Testar alertas"."""
    prob = {"ok": True, "acerto": 0.58, "inf": 0.55, "sup": 0.61, "n": 320}
    placar = {"WIN": 3, "LOSS": 1, "EMPATE": 0}
    return [
        aviso(
            "formando",
            **texto_formando("Tendência + recuo à média", "EUR/USD", "CALL", 78),
            som="formando",
            notificar=True,
            direcao="CALL",
        ),
        aviso(
            "entrada", **texto_entrada("CALL", "EUR/USD", 1, prob), som="entrada_call", notificar=True, direcao="CALL"
        ),
        aviso("entrada", **texto_entrada("PUT", "EUR/USD", 1, prob), som="entrada_put", notificar=True, direcao="PUT"),
        aviso(
            "resultado",
            **texto_resultado("WIN", "Tendência + recuo à média", "EUR/USD", placar),
            som="resultado",
            notificar=True,
        ),
    ]


# --------------------------------------------------------------------------- líder com histerese
@dataclass
class SeletorLider:
    """Escolhe a estratégia líder entre as COMPROVADAS e marcadas, sem trocar a cada vela.

    * A líder atual perde o posto NA HORA se deixar de ser comprovada (ou for desmarcada).
    * Outra comprovada só assume se ficar no topo por `velas_confirmacao` velas fechadas seguidas,
      ou se o limite inferior do IC dela superar o da líder em pelo menos `margem_ic`.
    """

    velas_confirmacao: int = LIDER_VELAS_CONFIRMACAO
    margem_ic: float = LIDER_MARGEM_IC
    atual: str | None = None
    desafiante: str | None = None
    contagem: int = 0

    def atualizar(self, ranking: dict, ativas: set | None = None, contar: bool = True) -> dict:
        """Chamar UMA vez por vela fechada (`contar=True`). Com `contar=False` (ex.: o usuário desmarcou
        uma estratégia) só corrige uma líder inválida, sem avançar a confirmação da desafiante."""
        be, min_ops = ranking["break_even"], ranking["min_ops"]
        comprovadas = [
            linha
            for linha in ranking["linhas"]
            if comprovada(linha, be, min_ops) and (ativas is None or linha["id"] in ativas)
        ]
        anterior = self.atual
        if not comprovadas:
            self._definir(None)
        else:
            topo = comprovadas[0]
            atual = next((linha for linha in comprovadas if linha["id"] == self.atual), None)
            if atual is None:
                self._definir(topo["id"])
            elif topo["id"] == self.atual:
                self.desafiante, self.contagem = None, 0
            elif contar:
                if topo["janela"]["ic_inf"] - atual["janela"]["ic_inf"] >= self.margem_ic:
                    self._definir(topo["id"])
                else:
                    if self.desafiante == topo["id"]:
                        self.contagem += 1
                    else:
                        self.desafiante, self.contagem = topo["id"], 1
                    if self.contagem >= self.velas_confirmacao:
                        self._definir(topo["id"])
        return {
            "lider": self.atual,
            "anterior": anterior,
            "trocou": self.atual != anterior,
            "desafiante": self.desafiante,
            "contagem": self.contagem,
            "faltam": (self.velas_confirmacao - self.contagem) if self.desafiante else None,
        }

    def _definir(self, id_: str | None) -> None:
        self.atual, self.desafiante, self.contagem = id_, None, 0


# --------------------------------------------------------------------------- motor de avisos
@dataclass
class MotorAvisos:
    """Estado dos avisos de uma sessão (uma aba). Garante: só a líder, uma vez por vela, sem repetir."""

    limite: int = PROGRESSO_LIMITE
    avisar_obs: bool = False  # candidatas não comprovadas (DESLIGADO por padrão)
    vela_formando: int | None = None  # vela (epoch de abertura) do último aviso de formação
    vela_entrada: int | None = None  # vela em que a entrada foi avisada
    vela_obs: int | None = None
    placar: dict = field(default_factory=lambda: {"WIN": 0, "LOSS": 0, "EMPATE": 0})

    def formacao(self, ver: dict, progresso: dict | None, vela: int, ativo: str) -> list[dict]:
        """A cada atualização da vela em formação. `ver`: veredito montado; `vela`: epoch da vela atual."""
        if not progresso or progresso.get("pct", 0) < self.limite:
            return []
        if ver.get("estado") == "PREPARANDO" and ver.get("comprovada"):
            if vela in (self.vela_formando, self.vela_entrada):
                return []
            self.vela_formando = vela
            return [
                aviso(
                    "formando",
                    **texto_formando(ver["nome"], ativo, progresso.get("dir"), progresso["pct"]),
                    som="formando",
                    notificar=True,
                    direcao=progresso.get("dir"),
                    vela=vela,
                )
            ]
        if ver.get("estado") == "OBSERVACAO" and self.avisar_obs and not ver.get("comprovada"):
            if vela == self.vela_obs:
                return []
            self.vela_obs = vela
            return [
                aviso(
                    "observacao",
                    **texto_observacao(ver["nome"], ativo, progresso.get("dir"), "formando"),
                    som="observacao",
                    notificar=True,
                    direcao=progresso.get("dir"),
                    vela=vela,
                )
            ]
        return []

    def fechamento(
        self, ver: dict, vela: int, ativo: str, troca: dict | None = None, nomes: dict | None = None
    ) -> list[dict]:
        """No fechamento de uma vela. `vela`: epoch da vela que ABRE agora (a da entrada)."""
        saida = []
        if troca and troca.get("trocou"):
            novo = (nomes or {}).get(troca["lider"], troca["lider"]) if troca["lider"] else None
            texto = f"Líder agora: {novo}" if novo else "Líder agora: nenhuma (sem vantagem comprovada)"
            saida.append(aviso("lider", "Líder agora", texto, vela=vela))
        estado = ver.get("estado")
        if estado == "ENTRAR" and ver.get("comprovada") and ver.get("dir") and vela != self.vela_entrada:
            self.vela_entrada = vela
            d = ver["dir"]
            saida.append(
                aviso(
                    "entrada",
                    **texto_entrada(d, ativo, ver.get("expiracao", 1), ver.get("prob")),
                    som="entrada_call" if d == "CALL" else "entrada_put",
                    notificar=True,
                    direcao=d,
                    vela=vela,
                )
            )
        elif estado == "CONFLITO":
            saida.append(aviso("conflito", "CONFLITO, não entrar", ver.get("frase", ""), vela=vela))
        elif (
            estado == "OBSERVACAO"
            and self.avisar_obs
            and ver.get("dir")
            and not ver.get("comprovada")
            and vela != self.vela_obs
            and ver.get("quando") == "agora"
        ):
            self.vela_obs = vela
            saida.append(
                aviso(
                    "observacao",
                    **texto_observacao(ver["nome"], ativo, ver["dir"], "agora"),
                    som="observacao",
                    notificar=True,
                    direcao=ver["dir"],
                    vela=vela,
                )
            )
        return saida

    def resultado(self, op: dict, resultado: str, ativo: str) -> list[dict]:
        """Resultado de uma operação. Só as entradas avisadas (principal) geram aviso e contam no placar."""
        if not op.get("principal") or resultado not in self.placar:
            return []
        self.placar[resultado] += 1
        return [
            aviso(
                "resultado",
                **texto_resultado(resultado, op.get("nome", ""), ativo, self.placar),
                som="resultado",
                notificar=True,
                direcao=op.get("dir"),
            )
        ]
