"""Menu de terminal: baixar velas da Deriv e rodar backtests."""

import os
import sys
from collections import defaultdict

import websockets

from binarias import backtest as bt
from binarias import dados
from binarias import ranking as rk
from binarias.config import JANELA_RANKING, MIN_OPERACOES, PASTA_RESULTADOS, TIMEFRAMES_PRONTOS
from binarias.deriv import DerivErro
from binarias.estrategias import ESTRATEGIAS
from binarias.log import configurar_log, obter
from binarias.timeframes import GRANULARIDADES_DERIV, nome_timeframe, parse_timeframe

log = obter("menu")
ERROS_DERIV = (DerivErro, OSError, ValueError, websockets.WebSocketException)  # rede, Deriv ou dado inválido


# --------------------------------------------------------------------------- #
# Helpers de entrada
# --------------------------------------------------------------------------- #
def perguntar(msg: str, padrao=None) -> str:
    """Lê uma resposta do terminal (Enter = padrão)."""
    sufixo = f" [{padrao}]" if padrao is not None else ""
    resp = input(f"{msg}{sufixo}: ").replace("﻿", "").strip()
    return resp if resp else ("" if padrao is None else str(padrao))


def perguntar_numero(msg: str, padrao, tipo=int, minimo=None, maximo=None):
    """Lê um número dentro da faixa, repetindo até ser válido."""
    while True:
        try:
            valor = tipo(perguntar(msg, padrao).replace(",", "."))
            if (minimo is not None and valor < minimo) or (maximo is not None and valor > maximo):
                raise ValueError
            return valor
        except ValueError:
            if maximo is not None:
                faixa = f" entre {minimo} e {maximo}"
            else:
                faixa = f" >= {minimo}" if minimo is not None else ""
            print(f"  Valor inválido. Digite um número{faixa}.")


def escolher_da_lista(titulo: str, itens: list[str], permitir_voltar=True) -> int | None:
    """Menu numerado; devolve o índice escolhido (None = voltar)."""
    print(f"\n{titulo}")
    for i, item in enumerate(itens, 1):
        print(f"  {i:>3}) {item}")
    if permitir_voltar:
        print("    0) Voltar")
    idx = perguntar_numero("Escolha", None if permitir_voltar else 1, int, 0 if permitir_voltar else 1, len(itens))
    return None if idx == 0 else idx - 1


# --------------------------------------------------------------------------- #
# Escolha de ativo e timeframe
# --------------------------------------------------------------------------- #
def escolher_ativo() -> str | None:
    """Escolha do ativo por mercado, busca ou código."""
    print("\nBuscando ativos na Deriv...")
    try:
        ativos = dados.listar_ativos()
    except ERROS_DERIV as e:
        log.warning("Erro ao buscar ativos: %s", e)
        return perguntar("Digite o código do ativo manualmente (ex: R_100, frxEURUSD)") or None

    def fmt(a):
        status = "aberto" if a.get("exchange_is_open") else "fechado"
        return f"{a['display_name']:<35} {a['symbol']:<18} ({status})"

    por_mercado = defaultdict(list)
    for a in ativos:
        por_mercado[a.get("market_display_name", "Outros")].append(a)
    mercados = sorted(por_mercado)

    while True:
        print(f"\n{len(ativos)} ativos disponíveis.")
        opcoes = [f"{m} ({len(por_mercado[m])})" for m in mercados]
        opcoes += ["Buscar por nome/código", "Digitar código manualmente"]
        idx = escolher_da_lista("Escolha o mercado:", opcoes)
        if idx is None:
            return None
        if idx == len(mercados) + 1:
            return perguntar("Código do ativo (ex: R_100, frxEURUSD)") or None
        if idx == len(mercados):
            termo = perguntar("Texto para buscar").lower()
            lista = [a for a in ativos if termo in a["display_name"].lower() or termo in a["symbol"].lower()]
            if not lista:
                print("Nenhum ativo encontrado.")
                continue
        else:
            lista = por_mercado[mercados[idx]]
        lista = sorted(lista, key=lambda a: (a.get("submarket_display_name", ""), a["display_name"]))
        escolha = escolher_da_lista("Escolha o ativo:", [fmt(a) for a in lista])
        if escolha is not None:
            return lista[escolha]["symbol"]


def escolher_timeframe() -> str | None:
    """Escolha do tempo gráfico (pronto ou personalizado)."""
    opcoes = []
    for tf in TIMEFRAMES_PRONTOS:
        nativo = "" if parse_timeframe(tf) in GRANULARIDADES_DERIV else "  (agregado)"
        opcoes.append(f"{tf}{nativo}")
    opcoes.append("Personalizado (ex: M7, M20, M45, H3, H6, H12)")
    idx = escolher_da_lista("Escolha o tempo gráfico:", opcoes)
    if idx is None:
        return None
    if idx < len(TIMEFRAMES_PRONTOS):
        return TIMEFRAMES_PRONTOS[idx]
    while True:
        tf = perguntar("Digite o timeframe (M=minutos, H=horas, D=dias)").upper()
        try:
            return nome_timeframe(parse_timeframe(tf))
        except ValueError as e:
            print(f"  {e}")


# --------------------------------------------------------------------------- #
# Fluxos do menu
# --------------------------------------------------------------------------- #
def fluxo_baixar():
    """Baixa velas e oferece rodar o backtest."""
    simbolo = escolher_ativo()
    if not simbolo:
        return
    tf = escolher_timeframe()
    if not tf:
        return
    qtd = perguntar_numero("Quantidade de velas", 1000, int, 1)
    print(f"\nBaixando {qtd} velas de {simbolo} em {tf}...")
    try:
        df = dados.baixar_velas(simbolo, tf, qtd)
    except ERROS_DERIV as e:
        log.error("Falha ao baixar %s %s: %s", simbolo, tf, e)
        print(f"Erro: {e}")
        return
    caminho = dados.salvar_csv(df, simbolo, tf)
    print(f"{len(df)} velas salvas em: {caminho}")
    if len(df) < qtd:
        print(f"Aviso: a Deriv só tinha {len(df)} velas disponíveis para esse ativo/timeframe.")
    print(f"Período: {df['datetime'].iloc[0]}  ->  {df['datetime'].iloc[-1]} (UTC)")
    if perguntar("Rodar backtest com esses dados agora? (s/n)", "s").lower().startswith("s"):
        fluxo_backtest(os.path.basename(caminho))


def configurar_backtest(com_gale: bool = True) -> bt.ConfigBacktest:
    """Pergunta os parâmetros do backtest."""
    print("\nConfiguração do backtest (Enter mantém o padrão):")
    p = bt.ConfigBacktest()
    gales = perguntar_numero("Quantidade de martingales (0 = sem gale)", p.gales, int, 0, 10) if com_gale else 0
    return bt.ConfigBacktest(
        expiracao=perguntar_numero("Expiração (em velas)", p.expiracao, int, 1),
        payout=perguntar_numero("Payout em % (ex: 85)", round(p.payout * 100), float, 1, 500) / 100,
        valor_entrada=perguntar_numero("Valor da entrada", p.valor_entrada, float, 0.01),
        gales=gales,
        fator_gale=perguntar_numero("Multiplicador do gale", p.fator_gale, float, 1) if gales else p.fator_gale,
        banca_inicial=perguntar_numero("Banca inicial", p.banca_inicial, float, 0),
        empate="perde"
        if perguntar("Preço igual na expiração: (d)evolve ou (p)erde?", "d").lower().startswith("p")
        else "devolve",
    )


def escolher_csv() -> str | None:
    """Escolha de um CSV salvo em data/."""
    csvs = dados.listar_csvs()
    if not csvs:
        print("\nNenhum CSV em data/. Baixe dados primeiro.")
        return None
    idx = escolher_da_lista("Escolha o arquivo de dados:", csvs)
    return None if idx is None else csvs[idx]


def fluxo_backtest(arquivo: str | None = None):
    """Backtest de uma estratégia (ou comparativo de todas)."""
    arquivo = arquivo or escolher_csv()
    if not arquivo:
        return
    df = dados.carregar_csv(arquivo)
    print(f"\n{arquivo}: {len(df)} velas carregadas.")

    nomes = [f"{e.nome} - {e.descricao}" for e in ESTRATEGIAS] + ["TODAS (comparar com parâmetros padrão)"]
    idx = escolher_da_lista("Escolha a estratégia:", nomes)
    if idx is None:
        return
    cfg = configurar_backtest()
    base = os.path.splitext(arquivo)[0]

    if idx == len(ESTRATEGIAS):
        resultados = {}
        for est in ESTRATEGIAS:
            try:
                resultados[est.nome] = bt.executar(df, est.gerar_sinais(df), cfg)
            except Exception:
                log.exception("Estratégia %s falhou em %s", est.id, arquivo)
        tabela = bt.comparar(resultados)
        print("\n" + tabela.to_string())
        print(
            "\nAtenção: escolher a 'melhor' desta tabela e usar daqui pra frente é otimizar no passado.\n"
            "Use a validação walk-forward (python validar.py) antes de confiar em qualquer uma."
        )
        caminho = os.path.join(PASTA_RESULTADOS, f"{base}_comparativo.csv")
        tabela.to_csv(caminho)
        print(f"\nComparativo salvo em: {caminho}")
        return

    est = ESTRATEGIAS[idx]
    params = {}
    if est.parametros:
        print(f"\nParâmetros de '{est.nome}':")
        for k, v in est.parametros.items():
            params[k] = perguntar_numero(f"  {k}", v, type(v))
    res = bt.executar(df, est.gerar_sinais(df, **params), cfg)
    bt.imprimir_resumo(f"{est.nome} | {arquivo}", res, cfg)
    if not res.operacoes.empty:
        print("\nÚltimas operações:")
        print(res.operacoes.drop(columns=["idx_sinal", "idx_fim"]).tail(10).to_string(index=False))
        print(f"\nOperações salvas em: {bt.salvar_operacoes(res, f'{base}_{est.id}_operacoes.csv')}")


def imprimir_ranking(r: dict, titulo: str) -> None:
    """Mostra o ranking e o critério de vantagem."""
    import pandas as pd

    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(f"\n{titulo}\n" + rk.tabela(r).drop(columns=["erro"]).to_string(index=False))
    print(f"\nCritério: {r['criterio']}")
    if r["melhor"]:
        nome = next(l["nome"] for l in r["linhas"] if l["id"] == r["melhor"])
        print(f"MELHOR DO MOMENTO: {nome}")
    else:
        print("SEM VANTAGEM COMPROVADA: nenhuma estratégia passou no critério. Não há vencedora.")
    print("Lembrete: com 11 estratégias testadas, uma pode passar por sorte. Confirme com python validar.py.")


def fluxo_ranking(arquivo: str | None = None):
    """Ranking honesto (janela recente x histórico, IC 95%)."""
    arquivo = arquivo or escolher_csv()
    if not arquivo:
        return
    df = dados.carregar_csv(arquivo)
    janela = perguntar_numero("Janela recente (velas)", JANELA_RANKING, int, 10)
    min_ops = perguntar_numero("Mínimo de operações na janela", MIN_OPERACOES, int, 1)
    cfg = bt.ConfigBacktest(
        expiracao=perguntar_numero("Expiração (em velas)", 1, int, 1),
        payout=perguntar_numero("Payout em % (ex: 85)", 85, float, 1, 500) / 100,
    )
    r = rk.calcular_ranking(df, cfg, janela, min_ops)
    imprimir_ranking(r, f"Ranking | {arquivo} | {len(df)} velas | janela {r['janela']}")
    caminho = os.path.join(PASTA_RESULTADOS, f"{os.path.splitext(arquivo)[0]}_ranking.csv")
    rk.tabela(r).to_csv(caminho, index=False)
    print(f"Ranking salvo em: {caminho}")


def fluxo_validacao():
    """Roda a validação walk-forward (validar.py)."""
    import validar

    cache = perguntar("Reaproveitar CSVs já baixados, se houver? (s/n)", "s").lower().startswith("s")
    payout = perguntar_numero("Payout em % (ex: 85)", 85, float, 1, 500)
    argv = sys.argv
    sys.argv = ["validar.py", "--payout", str(payout)] + (["--usar-cache"] if cache else [])
    try:
        validar.main()
    finally:
        sys.argv = argv


def main():
    """Menu principal do terminal."""
    configurar_log()
    opcoes = {
        "1": ("Baixar velas (escolher ativo e tempo gráfico)", fluxo_baixar),
        "2": ("Rodar backtest em um CSV salvo", fluxo_backtest),
        "3": (
            "Listar CSVs salvos",
            lambda: print("\n" + ("\n".join(f"  - {c}" for c in dados.listar_csvs()) or "  (nenhum)")),
        ),
        "4": ("Ranking de estratégias (janela recente x histórico, IC 95%)", fluxo_ranking),
        "5": ("Validação walk-forward (4 pares, 20000 velas M5)", fluxo_validacao),
    }
    while True:
        print("\n" + "=" * 40)
        print("   BACKTEST OPÇÕES BINÁRIAS - DERIV")
        print("=" * 40)
        for k, (texto, _) in opcoes.items():
            print(f"  {k}) {texto}")
        print("  0) Sair")
        op = perguntar("Opção")
        if op == "0":
            break
        if op not in opcoes:
            print("Opção inválida.")
            continue
        try:
            opcoes[op][1]()
        except KeyboardInterrupt:
            print("\nOperação cancelada.")
        except Exception as e:  # um erro num fluxo não derruba o menu
            log.exception("Erro no menu (opção %s)", op)
            print(f"\nErro: {e}\n(detalhes em resultados/erros.log)")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        sys.exit(0)
