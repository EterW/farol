"""Registro dos sinais ao vivo (resultados/sinais_ao_vivo.csv) e reconciliação dos pendentes.

* Todo sinal é gravado NA HORA com resultado PENDENTE. Ao expirar, a própria sessão (ou o coletor) troca
  para WIN/LOSS/EMPATE. Se a página fechar, o ativo/tempo trocar ou o PC desligar antes disso, a linha
  continua PENDENTE e a RECONCILIAÇÃO a resolve depois com as velas históricas da Deriv (a mesma regra do
  backtest: entra na abertura da vela seguinte ao sinal, sai no fechamento da vela de expiração).
* Só vira CANCELADO se a Deriv não tiver mais as velas do período; o motivo fica registrado.
* Preço de saída igual ao de entrada é sempre gravado como EMPATE (o dado bruto). A regra da corretora
  ("empate devolve" ou "empate perde", que é a da Deriv Rise/Fall) é aplicada só nos relatórios.
* Nenhuma linha é apagada. Arquivo com cabeçalho antigo é copiado para backups/ e convertido.
* Escritas são atômicas (arquivo temporário + os.replace) e protegidas por uma trava entre processos
  (o site e o coletar.py podem gravar no mesmo arquivo).
"""

import contextlib
import csv
import os
import shutil
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd

from .backtest import resolver
from .config import BASE_DIR, PASTA_RESULTADOS
from .deriv import ConexaoPerdida, DerivErro, vela_de_dict
from .log import obter
from .timeframes import agregar, granularidade_base, parse_timeframe

log = obter("registro")

CSV_SINAIS = os.path.join(PASTA_RESULTADOS, "sinais_ao_vivo.csv")
PASTA_BACKUPS = os.path.join(BASE_DIR, "backups")

COLUNAS_ANTIGAS = [
    "data_sinal",
    "data_entrada",
    "ativo",
    "timeframe",
    "estrategia",
    "principal",
    "direcao",
    "expiracao",
    "preco_entrada",
    "preco_saida",
    "resultado",
]
COLUNAS_CSV = [
    "id",
    *COLUNAS_ANTIGAS,
    "estrategia_id",
    "evento_id",  # ativo|tempo gráfico|vela do sinal (epoch)
    "n_estrategias_no_evento",
    "concordancia",  # quantas estratégias do evento apontam a MESMA direção desta linha (inclui ela)
    "hora_local",
    "lider",
    "estado_veredito",  # ENTRAR / PREPARANDO / AGUARDAR / CONFLITO / OBSERVACAO
    "probabilidade_estimada_no_momento",
    "payout",
    "controle",  # estratégia de controle (dispara em > 30% das velas): régua, nunca líder
    "preco_aviso",  # último preço no instante em que o sinal foi detectado
    "latencia_ms",  # do início da vela de entrada até a detecção do sinal
    "filtro_liquidez",
    "filtro_volatilidade",
    "filtro_variacao",
    "filtro_passaria",
    "origem",  # navegador / coletor / migracao
    "config_id",  # pré-registro do coletor (vazio = navegador, sem pré-registro)
    "resolucao",  # ao_vivo / reconciliacao
    "motivo",
    "resolvido_em",
]
RESULTADOS_FINAIS = ("WIN", "LOSS", "EMPATE")
PENDENTE, CANCELADO = "PENDENTE", "CANCELADO"
MOTIVO_ANTIGO = "cancelado na versão antiga (troca de ativo/tempo ou página fechada); reaberto para reconciliação"
TEXTO_RECONCILIADO = "resolvido na reconciliação"

RECONCILIAR_FOLGA = 20.0  # s depois do fim da vela de expiração antes de buscar o histórico
RECONCILIAR_DESISTIR = 86400.0  # s: vela que a Deriv ainda não devolveu depois disso -> CANCELADO
MAX_VELAS_PEDIDO = 850  # a API pública devolve ~900 velas por resposta


def fmt_data(epoch: int) -> str:
    """Epoch -> 'AAAA-MM-DD hh:mm:ss' (UTC)."""
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def epoch_de(texto: str) -> int:
    """'AAAA-MM-DD hh:mm:ss' (UTC) -> epoch."""
    return int(datetime.strptime(texto.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())


def hora_local(epoch: int) -> str:
    """Horário LOCAL do computador (a coluna data_* fica em UTC)."""
    return datetime.fromtimestamp(int(epoch)).astimezone().strftime("%Y-%m-%d %H:%M")


def evento_id(ativo: str, timeframe: str, epoch_sinal: int) -> str:
    """Identificador da vela do sinal: várias estratégias na mesma vela são UM evento."""
    return f"{ativo}|{timeframe}|{int(epoch_sinal)}"


def novo_id() -> str:
    """Identificador curto e único de uma linha."""
    return uuid.uuid4().hex[:12]


def campos_evento(direcoes: dict[str, str]) -> dict[str, dict]:
    """{id: direção} das estratégias registradas numa vela -> n_estrategias_no_evento e concordância."""
    n = len(direcoes)
    contagem: dict[str, int] = defaultdict(int)
    for d in direcoes.values():
        contagem[d] += 1
    return {k: {"n_estrategias_no_evento": n, "concordancia": contagem[d]} for k, d in direcoes.items()}


def linhas_do_evento(
    *,
    ativo: str,
    timeframe: str,
    seg: int,
    expiracao: int,
    payout: float,
    t_sinal: int,
    direcoes: dict[str, str],
    ranking: dict,
    lider: str | None,
    estado_veredito: str,
    principais: set[str],
    preco_aviso: float | None,
    agora: float,
    filtros: dict,
    origem: str,
    config_id: str,
) -> list[dict]:
    """Linhas PENDENTE para as operações abertas numa vela (uma por estratégia). Usado pelo site e pelo coletor."""
    from .estrategias import POR_ID  # import tardio: evita ciclo no carregamento

    por_id = {l["id"]: l for l in ranking.get("linhas", [])}
    campos = campos_evento(direcoes)
    t_ent = int(t_sinal) + int(seg)
    latencia = round((agora - t_ent) * 1000)
    ev = evento_id(ativo, timeframe, t_sinal)
    linhas = []
    for est_id, d in direcoes.items():
        lr = por_id.get(est_id) or {}
        acerto = (lr.get("janela") or {}).get("acerto")
        linhas.append(
            {
                "id": novo_id(),
                "data_sinal": fmt_data(t_sinal),
                "data_entrada": fmt_data(t_ent),
                "ativo": ativo,
                "timeframe": timeframe,
                "estrategia": POR_ID[est_id].nome if est_id in POR_ID else est_id,
                "estrategia_id": est_id,
                "principal": "sim" if est_id in principais else "não",
                "direcao": d,
                "expiracao": int(expiracao),
                "preco_entrada": "",
                "preco_saida": "",
                "resultado": PENDENTE,
                "evento_id": ev,
                **campos[est_id],
                "hora_local": hora_local(t_ent),
                "lider": "sim" if est_id == lider else "não",
                "estado_veredito": estado_veredito,
                "probabilidade_estimada_no_momento": "" if acerto is None else round(float(acerto), 4),
                "payout": round(float(payout), 4),
                "controle": "sim" if lr.get("controle") else "não",
                "preco_aviso": "" if preco_aviso is None else preco_aviso,
                "latencia_ms": latencia,
                **filtros,
                "origem": origem,
                "config_id": config_id,
                "resolucao": "",
                "motivo": "",
                "resolvido_em": "",
            }
        )
    return linhas


# --------------------------------------------------------------------------- trava entre processos
class _Trava:
    """Arquivo .lock criado com O_EXCL (funciona entre processos no Windows e no Linux)."""

    def __init__(self, caminho: str, espera: float = 10.0, velha: float = 30.0):
        self.caminho, self.espera, self.velha = caminho + ".lock", espera, velha
        self.local = threading.Lock()

    def __enter__(self):
        self.local.acquire()
        limite = time.monotonic() + self.espera
        while True:
            try:
                fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                with contextlib.suppress(OSError):
                    if time.time() - os.path.getmtime(self.caminho) > self.velha:
                        os.remove(self.caminho)  # trava esquecida por um processo que morreu
                        continue
                if time.monotonic() > limite:
                    self.local.release()
                    raise TimeoutError(f"arquivo travado: {self.caminho}") from None
                time.sleep(0.05)

    def __exit__(self, *_):
        with contextlib.suppress(OSError):
            os.remove(self.caminho)
        self.local.release()


# --------------------------------------------------------------------------- conversão do arquivo antigo
def _completar_antiga(linha: dict) -> dict:
    """Linha do formato antigo -> formato novo (o que dá para derivar; o resto fica vazio)."""
    nova = dict.fromkeys(COLUNAS_CSV, "")
    nova.update({c: linha.get(c, "") for c in COLUNAS_ANTIGAS})
    nova["id"] = novo_id()
    nova["origem"] = "navegador"
    with contextlib.suppress(ValueError, AttributeError):
        t = epoch_de(linha.get("data_sinal", ""))
        nova["evento_id"] = evento_id(linha["ativo"], linha["timeframe"], t)
        nova["hora_local"] = hora_local(epoch_de(linha.get("data_entrada", "")))
    from .estrategias import ESTRATEGIAS  # import tardio: evita ciclo no carregamento

    por_nome = {e.nome: e.id for e in ESTRATEGIAS}
    nova["estrategia_id"] = por_nome.get(linha.get("estrategia", ""), "")
    nova["controle"] = "sim" if nova["estrategia_id"] == "seguir_cor" else "não"
    if nova["resultado"] == CANCELADO:
        nova["resultado"] = PENDENTE
        nova["motivo"] = MOTIVO_ANTIGO
    elif nova["resultado"] in RESULTADOS_FINAIS:
        nova["resolucao"] = "ao_vivo"
    return nova


def converter_linhas_antigas(linhas: list[dict]) -> list[dict]:
    """Converte e calcula n_estrategias_no_evento e concordância a partir das linhas da mesma vela."""
    novas = [_completar_antiga(l) for l in linhas]
    por_evento: dict[str, list[dict]] = defaultdict(list)
    for l in novas:
        if l["evento_id"]:
            por_evento[l["evento_id"]].append(l)
    for grupo in por_evento.values():
        campos = campos_evento({str(i): l["direcao"] for i, l in enumerate(grupo)})
        for i, l in enumerate(grupo):
            l.update({k: str(v) for k, v in campos[str(i)].items()})
    return novas


# --------------------------------------------------------------------------- registro
class Registro:
    """O CSV de sinais ao vivo. Seguro para várias tarefas e para dois processos (site + coletor)."""

    def __init__(self, caminho: str = CSV_SINAIS, pasta_backups: str = PASTA_BACKUPS):
        self.caminho = caminho
        self.pasta_backups = pasta_backups
        self.trava = _Trava(caminho)
        self._atrasadas: list[dict] = []  # linhas que não puderam ser gravadas (arquivo aberto no Excel)
        self._resolucoes_atrasadas: dict[str, dict] = {}

    # ---------------------------------------------------------------- leitura / escrita brutas
    def _ler_bruto(self) -> tuple[list[str] | None, list[dict]]:
        if not os.path.exists(self.caminho):
            return None, []
        with open(self.caminho, encoding="utf-8-sig", newline="") as f:
            leitor = csv.DictReader(f)
            return list(leitor.fieldnames or []), list(leitor)

    def _escrever(self, linhas: list[dict]) -> None:
        tmp = self.caminho + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: acentos no Excel
            w = csv.DictWriter(f, fieldnames=COLUNAS_CSV, extrasaction="ignore")
            w.writeheader()
            for l in linhas:
                w.writerow({c: l.get(c, "") for c in COLUNAS_CSV})
        os.replace(tmp, self.caminho)

    def backup(self, sufixo: str = "") -> str | None:
        """Copia o CSV atual para backups/ (nada é apagado). Devolve o caminho da cópia."""
        if not os.path.exists(self.caminho):
            return None
        os.makedirs(self.pasta_backups, exist_ok=True)
        nome = os.path.basename(self.caminho).replace(".csv", f"_{time.strftime('%Y%m%d_%H%M%S')}{sufixo}.csv")
        destino = os.path.join(self.pasta_backups, nome)
        shutil.copy2(self.caminho, destino)
        return destino

    def _carregar_atual(self) -> list[dict]:
        """Linhas no formato novo; converte (com backup) se o arquivo estiver no formato antigo."""
        cab, linhas = self._ler_bruto()
        if cab is None:
            return []
        if cab == COLUNAS_CSV:
            return linhas
        copia = self.backup("_antes_da_migracao")
        if cab == COLUNAS_ANTIGAS:
            novas = converter_linhas_antigas(linhas)
        else:  # cabeçalho intermediário/desconhecido: preserva tudo o que tiver nome conhecido
            novas = []
            for l in linhas:
                n = {c: l.get(c, "") or "" for c in COLUNAS_CSV}
                n["id"] = n["id"] or novo_id()
                novas.append(n)
        self._escrever(novas)
        log.warning("Registro convertido para o formato novo (%d linhas). Cópia do original: %s", len(novas), copia)
        return novas

    # ---------------------------------------------------------------- API
    def ler(self) -> list[dict]:
        """Todas as linhas (formato novo)."""
        with self.trava:
            return self._carregar_atual()

    def migrar(self) -> dict:
        """Converte o arquivo para o formato novo, se preciso. Devolve um resumo."""
        cab, linhas = self._ler_bruto()
        if cab is None:
            return {"convertido": False, "linhas": 0}
        if cab == COLUNAS_CSV:
            return {"convertido": False, "linhas": len(linhas)}
        novas = self.ler()
        return {"convertido": True, "linhas": len(novas), "reabertas": sum(l["motivo"] == MOTIVO_ANTIGO for l in novas)}

    def adicionar(self, linhas: list[dict]) -> bool:
        """Acrescenta linhas (com as colunas faltantes vazias). False = ficou para depois (arquivo travado)."""
        completas = [{**{c: l.get(c, "") for c in COLUNAS_CSV}, "id": l.get("id") or novo_id()} for l in linhas]
        pendentes = self._atrasadas + completas
        try:
            with self.trava:
                self._carregar_atual()  # converte o formato antigo antes de acrescentar
                if not os.path.exists(self.caminho):
                    self._escrever(pendentes)
                else:
                    with open(self.caminho, "a", newline="", encoding="utf-8-sig") as f:
                        w = csv.DictWriter(f, fieldnames=COLUNAS_CSV, extrasaction="ignore")
                        for l in pendentes:
                            w.writerow(l)
            self._atrasadas = []
            if self._resolucoes_atrasadas:
                self.atualizar({})
            return True
        except (OSError, TimeoutError):
            log.exception(
                "Não foi possível gravar %s (aberto no Excel?). Nova tentativa no próximo registro.", self.caminho
            )
            self._atrasadas = pendentes
            return False

    def atualizar(self, resolucoes: dict[str, dict]) -> int:
        """Resolve linhas PENDENTE por id: {id: {resultado, preco_entrada, preco_saida, resolucao, motivo}}.
        Linhas já resolvidas não são tocadas (resolver duas vezes é inofensivo). Devolve quantas mudaram."""
        todas = {**self._resolucoes_atrasadas, **resolucoes}
        if not todas:
            return 0
        try:
            with self.trava:
                linhas = self._carregar_atual()
                mudou = 0
                for l in linhas:
                    r = todas.get(l["id"])
                    if r and l["resultado"] == PENDENTE:
                        l.update({k: ("" if v is None else v) for k, v in r.items()})
                        l["resolvido_em"] = fmt_data(int(time.time()))
                        mudou += 1
                if mudou:
                    self._escrever(linhas)
            self._resolucoes_atrasadas = {}
            return mudou
        except (OSError, TimeoutError):
            log.exception("Não foi possível atualizar %s (aberto no Excel?). Nova tentativa depois.", self.caminho)
            self._resolucoes_atrasadas = todas
            return 0

    def pendentes(self) -> list[dict]:
        """Linhas ainda sem resultado."""
        return [l for l in self.ler() if l.get("resultado") == PENDENTE]


# --------------------------------------------------------------------------- reconciliação
def momento_saida(linha: dict) -> int | None:
    """Epoch em que a vela de expiração da linha fecha (None se a linha estiver malformada)."""
    try:
        seg = parse_timeframe(linha["timeframe"])
        return epoch_de(linha["data_entrada"]) + max(1, int(linha.get("expiracao") or 1)) * seg
    except (KeyError, ValueError):
        return None


def _janelas(linhas: list[dict], seg: int, gran: int) -> list[tuple[int, int, list[dict]]]:
    """Agrupa as linhas de um ativo/tempo em janelas que cabem num pedido à Deriv: (início, fim, linhas)."""
    itens = []
    for l in linhas:
        ini = epoch_de(l["data_entrada"])
        fim = momento_saida(l)
        if fim is not None:
            itens.append((ini, fim, l))
    itens.sort(key=lambda x: x[0])
    grupos: list[tuple[int, int, list[dict]]] = []
    for ini, fim, l in itens:
        ini_base = ini - ini % seg  # início da vela do tempo gráfico (alinhado)
        if grupos and (max(grupos[-1][1], fim) - grupos[-1][0]) // gran <= MAX_VELAS_PEDIDO:
            g = grupos[-1]
            grupos[-1] = (g[0], max(g[1], fim), [*g[2], l])
        else:
            grupos.append((ini_base, fim, [l]))
    return grupos


async def _velas_periodo(pedir, simbolo: str, gran: int, ini: int, fim: int) -> list[list]:
    """Velas base de [ini, fim) com UM pedido (end + count, igual à paginação do download)."""
    contagem = (fim - ini) // gran + 2
    r = await pedir(
        {"ticks_history": simbolo, "style": "candles", "granularity": gran, "count": int(contagem), "end": int(fim)}
    )
    return [v for v in (vela_de_dict(c) for c in r.get("candles", [])) if ini <= v[0] < fim and v[0] % gran == 0]


def resolver_com_velas(linha: dict, velas_tf: pd.DataFrame) -> dict | None:
    """Resolução de uma linha com as velas do tempo gráfico (epoch -> open/close). None = vela ausente."""
    seg = parse_timeframe(linha["timeframe"])
    exp = max(1, int(linha.get("expiracao") or 1))
    t_ent = epoch_de(linha["data_entrada"])
    t_sai = t_ent + (exp - 1) * seg
    idx = velas_tf.set_index("epoch") if len(velas_tf) else None
    if idx is None or t_ent not in idx.index or t_sai not in idx.index:
        return None
    entrada = float(idx.at[t_ent, "open"])
    saida = float(idx.at[t_sai, "close"])
    return {
        "resultado": resolver(linha["direcao"], entrada, saida, "devolve"),  # EMPATE separado (dado bruto)
        "preco_entrada": entrada,
        "preco_saida": saida,
    }


async def reconciliar(registro: Registro, pedir, agora: float, folga: float = RECONCILIAR_FOLGA) -> dict:
    """Resolve as linhas PENDENTE cujo prazo já passou, buscando as velas históricas na Deriv.
    `pedir`: corrotina payload -> resposta (DerivHub.pedir ou DerivClient.pedir). Falha de conexão deixa a
    linha pendente para a próxima vez; só vira CANCELADO se a Deriv responder sem a vela do período."""
    vencidas = [l for l in registro.pendentes() if (momento_saida(l) or agora + 1) + folga <= agora]
    resumo = {"vencidas": len(vencidas), "resolvidas": 0, "canceladas": 0, "erros": 0}
    if not vencidas:
        return resumo
    por_serie: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for l in vencidas:
        por_serie[(l["ativo"], l["timeframe"])].append(l)
    resolucoes: dict[str, dict] = {}
    for (simbolo, tf), linhas in por_serie.items():
        try:
            seg = parse_timeframe(tf)
            gran = granularidade_base(seg)
        except ValueError:
            continue
        for ini, fim, grupo in _janelas(linhas, seg, gran):
            try:
                velas = await _velas_periodo(
                    pedir, simbolo, gran, ini, min(fim + 2 * seg, int(agora))
                )  # + folga: prova que o período passou
            except (DerivErro, ConexaoPerdida, TimeoutError) as e:
                log.warning("Reconciliação %s %s: %s (fica pendente)", simbolo, tf, e)
                resumo["erros"] += 1
                continue
            base = pd.DataFrame(velas, columns=["epoch", "open", "high", "low", "close"])
            fechadas, _ = agregar(base, seg, gran, agora)
            for l in grupo:
                r = resolver_com_velas(l, fechadas)
                if r is not None:
                    resolucoes[l["id"]] = {**r, "resolucao": "reconciliacao", "motivo": TEXTO_RECONCILIADO}
                    resumo["resolvidas"] += 1
                elif agora - (momento_saida(l) or agora) > RECONCILIAR_DESISTIR or (
                    len(base) and int(base["epoch"].max()) >= (momento_saida(l) or 0)
                ):
                    # a Deriv respondeu, tem velas DEPOIS do período, mas não a vela pedida (ou já passou 1 dia)
                    resolucoes[l["id"]] = {
                        "resultado": CANCELADO,
                        "resolucao": "reconciliacao",
                        "motivo": "a Deriv não tem mais a vela do período (mercado fechado ou dado indisponível)",
                    }
                    resumo["canceladas"] += 1
    registro.atualizar(resolucoes)
    if resumo["resolvidas"] or resumo["canceladas"]:
        log.info("Reconciliação: %s", resumo)
    return resumo
