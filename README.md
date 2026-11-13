# Backtest de Opções Binárias — Deriv

Backtest, ranking estatístico, validação walk-forward e modo ao vivo (site local) para estratégias
CALL/PUT com dados públicos da Deriv. **O mesmo código das estratégias roda no backtest, no ranking,
na validação e no ao vivo.**

> Aviso honesto: na última validação (4 pares Forex, 20000 velas M5, payout 85%) **nenhuma estratégia
> passou**. A ferramenta foi feita para dizer "sem vantagem comprovada" quando os dados não comprovam
> nada, e não para prometer assertividade.

## Instalação (Windows / PowerShell)
```powershell
cd C:\Users\Win11\backtest-binarias
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
Requer Python 3.10+ (testado com 3.12).

## Comandos
| Comando | O que faz |
|---|---|
| `python main.py` | Menu: baixar velas, backtest, ranking, validação |
| `python live.py` | Modo ao vivo em http://127.0.0.1:8000 (abre o navegador) |
| `python validar.py` | Validação completa (download + comparativo + walk-forward + relatório) |
| `python -m pytest` | Testes automáticos (estratégias, motor, ranking, hub, sessão, validação) |

### Menu (`python main.py`)
1. **Baixar velas**: mercado → ativo → tempo gráfico (M1…D1 ou personalizado, ex.: M7, M20, H6) → quantidade.
2. **Backtest**: uma estratégia (com parâmetros) ou TODAS; expiração, payout, entrada, gales, banca, empate.
3. **Listar CSVs**.
4. **Ranking**: janela recente × histórico com IC de Wilson 95% (veja abaixo).
5. **Validação walk-forward** (o mesmo que `python validar.py`).

### Modo ao vivo (`python live.py`)
```powershell
python live.py                          # abre o navegador
python live.py --porta 8080 --sem-navegador
```
`http://127.0.0.1:8000/?auto` conecta direto com a última escolha. Informe **Payout %**: ele define o break-even.

**Interface do Farol** (`static/index.html`, `static/app.css`, `static/app.js`; paleta e fontes só em `static/tema.css`):
- **Veredito** no topo, em português simples: `ENTRAR AGORA` (▲ COMPRA / ▼ VENDA), `SE PREPARANDO`, `AGUARDAR`
  (com o motivo), `CONFLITO, NÃO ENTRAR` e `MODO OBSERVAÇÃO` (melhor candidata, rotulada “NÃO COMPROVADA”, sem som).
  Sempre com probabilidade **estimada**, faixa de incerteza (Wilson 95%), nº de operações e break-even. A regra é
  aplicada no servidor (`binarias/veredito.py`), nunca no navegador.
- Modos **Simples** (padrão) e **Detalhado** (ranking visual, mercado em palavras simples, operações da sessão).
- Tour de 4 passos na primeira visita (reabra no **?**), **Alertas** com volume e teste.
- **Demonstração sem conexão**: `http://127.0.0.1:8000/?demo=entrar` (ou `preparando`, `aguardar`, `conflito`,
  `observacao`). Dados simulados, com faixa de aviso, mas passando pelas mesmas funções do ao vivo.
- Screenshots de revisão: `python tests/telas.py --url http://127.0.0.1:8000` → `resultados/telas/`
  (requer `pip install playwright`; usa o Edge do Windows).

Painéis (detalhes técnicos):
- **Sinal principal**: vem **só** da estratégia nº 1 do ranking daquele ativo/timeframe.
  - `SEM SINAL CONFIÁVEL NO MOMENTO`: nenhuma estratégia marcada tem vantagem comprovada. **Sem alerta de entrada.**
  - `AGUARDANDO` / `SE PREPARANDO` (som de preparo) / `ENTRAR AGORA` (som de entrada, só em vela fechada).
  - `CONFLITO, NÃO ENTRAR`: outra estratégia marcada com ≥ 30 operações e acerto acima do break-even
    aponta o lado oposto.
- **Análise de mercado**: tendência (preço × MM50 e inclinação da MM50 em ATRs), força (ADX 14),
  volatilidade (percentil do ATR 14 nas últimas 500 velas), vela atual e resumo em texto. O critério aparece na tela.
- **Top 3 ativos** (atualiza a cada vela fechada; clique para abrir): pontuação 0–100, com a regra visível na tela:
  mercado aberto (obrigatório), volatilidade saudável (25), tendência clara (25) e estratégia com vantagem
  comprovada (30 + até 20). Lista em `ATIVOS_SCANNER` (config ou variável de ambiente).
- **Ranking de estratégias**: operações, acerto, IC 95%, lucro (janela e histórico carregado), força e vantagem.
  Desmarcar uma estratégia tira ela da escolha da principal e do cálculo de conflito.
- **Status da conexão** com a Deriv no topo (conectado / reconectando / reconexões).
- **🔊 Testar alerta**: toca o som de preparo e o de entrada e envia uma notificação de teste (pede a permissão
  se precisar). Toca mesmo com o som desligado e avisa se o som, o áudio ou as notificações estiverem bloqueados.
- **👁 Modo observação** (desligado por padrão): quando **nenhuma** estratégia tem vantagem comprovada, o veredito
  mostra a melhor candidata do momento (cinza, borda âmbar, fita “NÃO COMPROVADA · apenas observação, não é
  recomendação”). Nunca toca som de entrada e não mexe no ENTRAR AGORA nem no CSV.

Cada sinal das estratégias marcadas vai para `resultados/sinais_ao_vivo.csv` depois da expiração
(WIN/LOSS/EMPATE, ou CANCELADO se você trocar de ativo antes). A coluna `principal` marca o sinal do painel principal.
Use esse arquivo para conferir, ao vivo, se o desempenho se mantém.

**Conexão com a Deriv**: o servidor usa **uma única conexão** para tudo (abas abertas + scanner). Cada
ativo é assinado uma vez só e compartilhado. A Deriv derruba a conexão pública a cada ~2 min, então o servidor
reconecta, reassina e preenche as velas do intervalo. Há intervalo mínimo entre requisições e backoff
exponencial em quedas repetidas e em `RateLimit`.

### Validação (`python validar.py`)
```powershell
python validar.py                                   # 20000 velas M5 de EURUSD, GBPUSD, USDJPY, AUDUSD
python validar.py --usar-cache                      # reaproveita data/*_M5_20000.csv
python validar.py --payout 80 --expiracao 2 --empate perde
python validar.py --ativos frxEURUSD,frxGBPUSD --velas 5000 --treino 0.7 --min-ops 100
```
- **Comparativo**: todas as estratégias, parâmetros padrão, todos os pares → `resultados/validacao_comparativo.csv`.
- **Walk-forward**: para cada estratégia e par, testa a grade de parâmetros **só nos 70% iniciais**
  e escolhe pelo limite inferior do IC; depois aplica nos **30% finais**, que nunca foram vistos na escolha.
  Treino e teste lado a lado → `resultados/validacao_walkforward.csv`.
- **Relatório** → `resultados/validacao_relatorio.csv` e `.txt`: quais estratégias **passam em todos os pares**
  (no teste: ≥ 100 operações e limite inferior do IC 95% acima do break-even). Se nenhuma passar, ele diz isso.
  Também mostra o efeito de seleção: a melhor no treino e o que aconteceu com ela no teste.

## Regras do ranking ("melhor do momento")
- Janela recente configurável (padrão **500 velas**, `JANELA_RANKING`) e histórico completo (no ao vivo:
  `N_HISTORICO` = 3000 velas carregadas).
- Uma estratégia só é a melhor do momento se, **na janela**, tiver **≥ 100 operações** (`MIN_OPERACOES`) **E** o
  **limite inferior do IC de Wilson 95%** do acerto ficar **acima do break-even** do payout: `1 / (1 + payout)`,
  ou seja 54,05% com 85%. Caso contrário, aparece **"sem vantagem comprovada"**.
- **Força**: a janela é comparada com o histórico anterior a ela (teste z de duas proporções, 5% unilateral):
  "perdendo força", "ganhando força", "estável" ou "dados insuficientes" (< 30 operações em algum lado).
- Sempre **sem gale**. Com 11 estratégias testadas, uma pode passar por sorte. Confirme com a validação.

## Regras do backtest
- Sinal no fechamento da vela *i* → entrada na **abertura da vela i+1** → expiração no fechamento da vela
  *i+expiração*. Operações que não terminam dentro dos dados são descartadas.
- Não abre nova operação com uma em andamento (gales incluídos). Um novo sinal pode sair no fechamento da
  vela de expiração. O modo ao vivo segue a mesma regra.
- **Empate** (saída = entrada): `devolve` (padrão) ou `perde` (regra Rise/Fall da Deriv). No menu, pergunte;
  na validação use `--empate perde`; no ao vivo defina a variável de ambiente `EMPATE=perde`.
- Limitações: o preço real de entrada é o próximo tick após a ordem (atraso/slippage não modelados); o
  modo ao vivo não faz martingale.

## Estrutura
```
main.py            Menu no terminal
live.py            Modo ao vivo (site local)
validar.py         Validação walk-forward
binarias/
  config.py        Todas as configurações (payout, janela, ativos do scanner, pastas...)
  log.py           Log de erros em resultados/erros.log
  timeframes.py    Parsing de timeframe e agregação de velas (igual no backtest e ao vivo)
  deriv.py         Cliente da Deriv para scripts (paginação, reconexão, backoff)
  hub.py           Conexão única compartilhada do modo ao vivo
  dados.py         Download e CSV
  indicadores.py   RSI, ATR, ADX, Bollinger, médias (todos causais)
  estrategias.py   Estratégias + preparo + grades de parâmetros
  backtest.py      Motor de backtest e regra de resultado (resolver)
  estatistica.py   Wilson, break-even, teste z
  ranking.py       Ranking honesto
  mercado.py       Análise de mercado
  scanner.py       Pontuação do Top 3
  sinal.py         Decisão do sinal único
  validacao.py     Comparativo + walk-forward + relatório
  sessao.py        Lógica de uma aba do modo ao vivo
  servidor.py      FastAPI
static/index.html  Página do modo ao vivo
tests/             Testes automáticos (inclui um servidor Deriv falso)
data/              CSVs baixados (ATIVO_TEMPO.csv)
resultados/        Backtests, rankings, validação, sinais_ao_vivo.csv, erros.log
```

## Criar sua estratégia
Em `binarias/estrategias.py`, escreva `minha(df, param=10)` devolvendo uma Series com `"CALL"`, `"PUT"` ou
`None` **usando só velas até a atual** (o teste `test_sem_lookahead` reprova quem olha o futuro). Opcionalmente,
escreva `minha_prep(df, param=10)` para o estado "se preparando". Depois registre:
```python
Estrategia("Minha", "MINHA", minha, {"param": 10}, preparo=minha_prep, grade={"param": [5, 10, 20]}),
```
Ela passa a valer automaticamente no backtest, no ranking, na validação e no ao vivo. Rode `python -m pytest`.

## Endpoint
API pública nova da Deriv: `wss://api.derivws.com/trading/v1/options/ws/public` (sem token). Ela devolve
no máximo ~900 velas por requisição; o download pagina sozinho. Para trocar o endpoint, defina `DERIV_WS_URL`.
