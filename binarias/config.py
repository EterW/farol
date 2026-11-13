"""Configurações gerais do projeto (um lugar só). Edite aqui ou use variáveis de ambiente."""
import os

# Endpoint público da nova API da Deriv (dados de mercado, sem login/token).
# O antigo wss://ws.derivws.com/websockets/v3?app_id=1089 deixou de responder (HTTP 520).
WS_URL = os.getenv("DERIV_WS_URL", "wss://api.derivws.com/trading/v1/options/ws/public")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_DADOS = os.path.join(BASE_DIR, "data")
PASTA_RESULTADOS = os.path.join(BASE_DIR, "resultados")
PASTA_STATIC = os.path.join(BASE_DIR, "static")
ARQUIVO_LOG = os.path.join(PASTA_RESULTADOS, "erros.log")

TIMEFRAMES_PRONTOS = ["M1", "M2", "M3", "M5", "M10", "M15", "M20", "M30", "H1", "H2", "H4", "H8", "D1"]

# --------------------------------------------------------------------------- backtest / ranking
PAYOUT_PADRAO = 0.85          # 0.85 = 85%
EXPIRACAO_PADRAO = 1          # em velas
# Preço de saída igual ao de entrada: "devolve" (stake devolvida, comum em várias corretoras)
# ou "perde" (regra Rise/Fall padrão da Deriv: só ganha se a saída for estritamente melhor).
EMPATE_PADRAO = os.getenv("EMPATE", "devolve")
JANELA_RANKING = 500          # "últimas N velas" do ranking
MIN_OPERACOES = 100           # mínimo de operações na janela para declarar vantagem
CONFIANCA = 0.95              # nível do intervalo de Wilson
Z_FORCA = 1.645               # z unilateral (5%) para "perdendo/ganhando força"
MIN_OPS_FORCA = 30            # mínimo de operações em cada lado para comparar força

# --------------------------------------------------------------------------- modo ao vivo
N_HISTORICO = 3000            # velas do timeframe carregadas por ativo ("histórico completo" ao vivo)
N_VELAS_GRAFICO = 600         # velas enviadas ao gráfico
N_VELAS_PREVIA = 400          # velas usadas na prévia "se a vela fechasse agora"
FOLGA_FECHAMENTO = 1.0        # s após o fim da vela para considerá-la fechada (ticks atrasados)
INTERVALO_MIN_REQUISICOES = 0.35   # s entre requisições na conexão da Deriv
CONFLITO_MIN_OPERACOES = 30   # estratégias com >= N ops e acerto acima do break-even contam para CONFLITO
ATIVOS_SCANNER = [s.strip() for s in os.getenv(
    "ATIVOS_SCANNER",
    "frxEURUSD,frxGBPUSD,frxUSDJPY,frxAUDUSD,frxEURGBP,frxEURJPY,frxGBPJPY").split(",") if s.strip()]

# --------------------------------------------------------------------------- validação
VALIDACAO_ATIVOS = ["frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD"]
VALIDACAO_TIMEFRAME = "M5"
VALIDACAO_VELAS = 20000
FRACAO_TREINO = 0.70


def garantir_pastas() -> None:
    os.makedirs(PASTA_DADOS, exist_ok=True)
    os.makedirs(PASTA_RESULTADOS, exist_ok=True)


garantir_pastas()
