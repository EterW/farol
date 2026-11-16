# Farol

**Sinais com evidência estatística, sem promessa.**

O Farol é uma ferramenta local de estudo para opções binárias (CALL/PUT) com dados públicos da Deriv:
backtest, ranking estatístico, validação walk-forward e um modo ao vivo no navegador. Ele só sugere
entrada quando a estratégia **líder** tem vantagem comprovada no histórico recente. Quando os dados não
comprovam nada, ele diz isso e fica em silêncio.

> **Aviso honesto.** Na última validação (4 pares Forex, 20.000 velas M5, payout 85%, **20 estratégias**,
> correção de Holm para 80 hipóteses) **nenhuma estratégia passou**, nem sem a correção. Toda probabilidade mostrada é *estimada* a partir do passado, com margem de erro. Nenhum sinal é
> garantia; opções binárias podem causar perda total do valor investido.

---

## Instalar (Windows / PowerShell)

```powershell
cd C:\Users\Win11\backtest-binarias
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt          # só o necessário para rodar
pip install -e ".[dev]"                  # opcional: testes, ruff, mypy, playwright (screenshots)
pip install -e ".[assistente]"           # opcional: assistente "Explique para mim" (SDK da Anthropic)
```

Requer Python 3.10+ (testado com 3.12).

## Rodar

| Comando | O que faz |
|---|---|
| `python live.py` | Modo ao vivo em http://127.0.0.1:8000 (abre o navegador) |
| `python live.py --porta 8080 --sem-navegador` | Outra porta, sem abrir o navegador |
| `python main.py` | Menu no terminal: baixar velas, backtest, ranking, validação |
| `python validar.py` | Validação completa (download + comparativo + walk-forward + relatório) |

Atalhos do modo ao vivo: `/?auto` conecta direto com a última escolha; `/?demo=entrar` (ou `preparando`,
`aguardar`, `conflito`, `observacao`) mostra uma **demonstração com dados simulados**, que passa pelas mesmas
funções do ao vivo e exibe uma faixa de aviso.

O servidor escuta só em `127.0.0.1` por padrão. Com `--host 0.0.0.0` ele fica acessível na rede **sem senha**
(o terminal avisa). `Ctrl+C` encerra de forma limpa (fecha a conexão com a Deriv e registra operações abertas
como `CANCELADO`).

## Testar

```powershell
python -m pytest                     # 280 testes (estratégias, indicadores, ranking, assistente, banca...)
python -m ruff check . ; python -m ruff format --check .
python -m mypy                       # checagem de tipos leve (pandas/numpy tratados como Any)
python live.py --porta 8765 --sem-navegador   # e, em outro terminal:
python tests/telas.py                # screenshots 1440/1920/390 dos 5 estados + checagens visuais
```

`tests/telas.py` falha se houver erro no console, rolagem horizontal, texto visível menor que 12px, veredito
fora da tela ao abrir ou se a barra compacta não aparecer ao rolar.

---

## Regras de honestidade (valem em todo o código)

1. **Vantagem comprovada** = na janela recente, **≥ 100 operações** (`MIN_OPERACOES`) **e** limite inferior do
   **IC de Wilson 95%** do acerto **acima do break-even** `1 / (1 + payout)` (54,05% com payout 85%) **e**
   p-valor binomial ajustado por **Holm** entre todas as estratégias testadas < 2,5% (testes múltiplos).
   Sem isso: "sem sinal confiável" e **nenhum aviso de entrada**.
2. **Uma estratégia líder** por ativo/tempo gráfico: a comprovada no topo do ranking. **Só ela** gera som e
   notificação. Troca de líder com **histerese**: a nova precisa ficar no topo por 3 velas fechadas seguidas ou
   ter o limite inferior do IC ≥ 2 p.p. maior; se a líder perder a vantagem, sai na hora.
3. **Conflito bloqueia a entrada**: se outra estratégia relevante (≥ 30 operações e acerto acima do break-even)
   aponta o lado oposto, a tela mostra `CONFLITO, NÃO ENTRAR` e nenhum aviso de entrada é enviado.
4. **Ranking nunca pelo percentual bruto**: ordem por status (comprovada primeiro), depois pelo **limite
   inferior do IC**, depois pelo nº de operações. Menos de 30 operações = grupo "Poucos dados" (em cinza).
5. Probabilidade sempre **estimada**, com faixa, nº de operações e break-even. Sem martingale no ranking.
   Nenhum texto promete lucro, "assertividade" ou percentuais mágicos (há teste automático para isso).
6. Tudo isso é decidido **no servidor** (`binarias/`), testável; o navegador só desenha e toca o que recebe.
7. **A IA nunca decide sinal nem prevê preço.** O assistente opcional só explica números já calculados, e o
   código descarta respostas com número, estratégia ou ativo inventado, previsão ou recomendação.

## Modo ao vivo: o que aparece na tela

- **Veredito** (sempre visível; vira uma barra fixa ao rolar): `ENTRAR AGORA` (▲ COMPRA / ▼ VENDA, com o tempo
  restante para entrar), `SE PREPARANDO`, `AGUARDAR` (com o motivo), `CONFLITO, NÃO ENTRAR` e `MODO OBSERVAÇÃO`
  (melhor candidata, rotulada "NÃO COMPROVADA", silenciosa).
- **Progresso de formação (0–100%)** da líder: `60% × condições cumpridas + 40% × proximidade do gatilho`, onde a
  proximidade mede quanto o fechamento da vela atual precisaria andar, em ATR, para todas as condições valerem
  (1 ATR ou mais = 0). As condições são exatamente as que geram o sinal. O "?" na tela explica a conta.
- **Avisos** (som + notificação, só da líder), em 3 momentos:
  1. *Formando*: "Farol: [estratégia] está se formando em [ativo]. Fique atento: o sinal pode sair na próxima vela."
     Uma vez por vela, quando o progresso passa do limite (padrão 70%, ajustável em **Alertas**).
  2. *Entrar agora*: "Entre AGORA: COMPRA ▲ em [ativo], expiração N vela(s). Probabilidade estimada X% (entre A% e
     B%, N operações)." Som diferente para compra e venda.
  3. *Resultado*: WIN/LOSS/EMPATE e o placar da sessão.
  Opção separada e **desligada por padrão**: "avisar também candidatas não comprovadas (só observação)", com som e
  título próprios ("OBSERVAÇÃO, sem vantagem comprovada"). **Testar alertas** dispara os 3 tipos com os textos reais.
- **Gráfico** (Lightweight Charts™ da TradingView): por padrão só a entrada avisada (★) e os sinais da líder.
  "Mostrar todos os sinais" agrupa por vela (uma seta com "×N"; a lista aparece no tooltip).
- **Top 3 ativos**: nota contínua de 0 a 100 (movimento, tendência, estratégia comprovada), desempate explícito e
  o motivo de cada parte da nota. Clique para abrir o ativo.
- **Detalhado**: ranking em grupos (recente × histórico), mercado em palavras simples com o resumo técnico
  explicado, e as operações da sessão.
- **Letra P/M/G** e modo Simples/Detalhado ficam salvos no navegador.

- **Minha banca** (dados só no navegador): entrada sugerida (% da banca, aviso acima de 5%), perda máxima do
  dia, parar após N losses seguidos, meta opcional. Ao atingir o limite: faixa "Limite do dia atingido: pare por
  hoje" e os avisos de entrada são silenciados **no servidor**. Simulador "e se" (Monte Carlo, entrada fixa, sem
  martingale; sugere o pior caso plausível da líder), diário com exportação CSV e curva da banca.
- **Explique para mim** (opcional, desligado sem chave): veja "Assistente" abaixo.
- **Aprender** (botão no topo): glossário com 25 termos (2 frases + exemplo), tour "Por que o Farol fica em
  silêncio" e a página `/como-decide` (dados → estratégias → ranking com margem de erro → validação → sinal).

Cada sinal das estratégias marcadas vai para `resultados/sinais_ao_vivo.csv` após a expiração (WIN, LOSS, EMPATE
ou CANCELADO). A coluna `principal` marca as entradas avisadas.

## Ranking, backtest e validação

- **Janela recente**: 1.500 velas (`JANELA_RANKING`); **histórico**: 3.000 velas carregadas (`N_HISTORICO`).
  Com 500 velas, só ~2 das 11 estratégias de então chegavam a 100 operações (medido em R_100 M1 e EUR/USD M5), o que tornava
  a regra quase impossível de cumprir. A regra de 100 operações **não foi relaxada**.
- **Força**: janela × histórico anterior a ela (teste z de duas proporções, 5% unilateral).
- **Backtest**: sinal no fechamento da vela *i* → entrada na abertura da vela *i+1* → expiração no fechamento da
  vela *i+expiração*. Sem operações sobrepostas. Empate: `devolve` (padrão) ou `perde` (`EMPATE=perde`).
- **Validação / laboratório** (`python validar.py`): escolhe parâmetros só nos 70% iniciais e mede nos 30%
  finais nunca vistos. Passa = em **todos** os pares, ≥ 100 operações, limite inferior do IC acima do break-even
  **e** p ajustado por Holm < 2,5%. O relatório informa quantas hipóteses (estratégia × par) e quantas
  combinações de parâmetros foram testadas, e quantas passariam sem correção, com Bonferroni, Holm e
  Benjamini-Hochberg (FDR).

### Estratégias (20)

Seguir cor, Reversão de sequência, Cruzamento de médias, RSI reversão, MHI 1, Tendência + recuo, Bollinger + RSI,
Pin Bar, Rompimento S/R, Rejeição S/R, Engolfo e, novas: **MACD cruzamento, MACD + tendência, Estocástico
reversão, SuperTrend + recuo, Keltner reversão, Keltner rompimento, Donchian após compressão, CCI reversão e
Williams %R + tendência**. Indicadores em `binarias/indicadores.py` (todos causais, testados truncando o futuro;
MACD e Estocástico também com valores de referência). **VWAP** está implementado, mas não é usado: a Deriv não
fornece volume. Ícones em `static/icones/` (`python ferramentas/gerar_icones.py`).

### Último laboratório (16/11/2026, dados de 04/08 a 12/11/2026)

4 pares (EUR/USD, GBP/USD, USD/JPY, AUD/USD), 20.000 velas M5, payout 85%, expiração 1 vela: 20 estratégias ×
4 pares = **80 hipóteses** fora da amostra, **360 combinações** avaliadas no treino. Vantagem no teste: **0/80**
sem correção, 0/80 com Bonferroni, Holm e FDR. Acerto médio no teste entre 48,3% e 52,4% (break-even 54,05%).
**Nenhuma estratégia passou.** Detalhes em `resultados/validacao_relatorio.txt`.

## Assistente "Explique para mim" (opcional)

- Desligado por padrão. Para ligar: `pip install -e ".[assistente]"`, copie `.env.example` para `.env`, preencha
  `ANTHROPIC_API_KEY` e reinicie. A chave fica só no servidor local (nunca no navegador nem no git).
- **Envio externo**: a cada pergunta, o Farol envia à API da Anthropic só números já calculados (ativo, tendência,
  veredito, probabilidade estimada com faixa e amostra, break-even) e a pergunta. Banca e diário nunca saem do
  navegador. A tela mostra esse aviso.
- **Custo**: cada chamada é paga. Controles no `.env`: modelo (`FAROL_ASSISTENTE_MODELO`, padrão
  `claude-opus-5-5`; Sonnet/Haiku custam menos), limite por hora (padrão 20), tempo limite e esforço. Há cache por
  ativo + tempo gráfico + vela + pergunta, e perguntas como "devo entrar?" são recusadas sem chamar a API.
- **Garantias** (no prompt e conferidas no código, `binarias/assistente.py`): até 5 linhas; descarta a resposta
  se houver número, estratégia ou ativo fora do JSON, previsão ("vai subir"), recomendação ou promessa, ou se não
  disser "sem vantagem comprovada" quando for o caso. Falha de rede, recusa ou limite = texto padrão do Farol.

## Estrutura

```
live.py                 Modo ao vivo (site local)
main.py                 Menu no terminal
validar.py              Validação walk-forward
pyproject.toml          Metadados, dependências e configuração de ruff, pytest e mypy
binarias/
  config.py             TODAS as configurações (janelas, mínimos, limites, pesos, conexão, pastas)
  estrategias.py        20 estratégias descritas por condições nomeadas (sinal = todas cumpridas)
  progresso.py          Progresso de formação (condições + distância ao gatilho em ATR)
  avisos.py             Estratégia líder com histerese e motor de avisos (formando/entrar/resultado)
  sinal.py              Decisão técnica (ENTRAR, PREPARANDO, CONFLITO...) a partir da líder
  veredito.py           Tradução para português simples, com a regra de honestidade reconferida
  ranking.py            Ranking honesto (Wilson, break-even, ordem por status e limite inferior)
  backtest.py           Motor de backtest e regra de resultado (a mesma do ao vivo)
  estatistica.py        Wilson, break-even, teste z
  indicadores.py        RSI, ATR, ADX, Bollinger, médias (todos causais)
  mercado.py            Análise de mercado com critério explícito
  scanner.py            Nota do Top 3
  timeframes.py         Timeframes e agregação de velas (igual no backtest e ao vivo)
  deriv.py / hub.py     Cliente para scripts / conexão única compartilhada do ao vivo
  dados.py              Download e CSV
  sessao.py             Uma aba do modo ao vivo
  servidor.py           FastAPI + WebSocket (valida toda entrada)
  demo.py               Cenários simulados da demonstração
  validacao.py          Comparativo, walk-forward, correção de testes múltiplos e relatório
  assistente.py         Assistente opcional: explica (não prevê), com validação da resposta
  risco.py              Minha banca: entrada, limites do dia e simulador (sem martingale)
  glossario.py          Glossário e tour "Por que o Farol fica em silêncio"
  log.py                Log em resultados/erros.log
static/                 index.html, app.js, extras.js (assistente, banca, glossário), app.css, tema.css,
                        como-decide.html, marca/ (logo) e icones/ (um SVG por estratégia)
ferramentas/            gerar_marca.py (logo, favicon) e gerar_icones.py (ícones das estratégias)
tests/                  Testes automáticos (com um servidor Deriv falso) e telas.py (screenshots)
data/, resultados/      CSVs baixados e saídas (fora do git)
```

## Criar sua estratégia

Em `binarias/estrategias.py`, escreva as condições e o sinal, usando **só velas até a atual**:

```python
def minha_condicoes(df, n=10):
    alta = df["close"] > df["close"].shift(n)
    return [_c(f"Fecha acima de {n} velas atrás", f"Fecha abaixo de {n} velas atrás", alta, ~alta)]


def minha(df, n=10):
    """Segue a direção das últimas N velas."""
    return _de_condicoes(minha_condicoes(df, n))


# registre em ESTRATEGIAS:
Estrategia("Minha", "MINHA", minha, {"n": 10}, condicoes=minha_condicoes, grade={"n": [5, 10, 20]})
```

Ela passa a valer no backtest, ranking, validação, progresso e ao vivo. `python -m pytest` reprova quem olha o
futuro e confere que o sinal é exatamente "todas as condições cumpridas".

## Limitações conhecidas

- Entrada simulada na abertura da vela seguinte; atraso e slippage reais não são modelados.
- Com 20 estratégias testadas, uma pode passar por sorte; a correção de Holm reduz (não elimina) esse risco e
  deixa a regra mais exigente. Use a validação.
- Assistente: custo por chamada na API da Anthropic e envio de dados calculados a um serviço externo. A
  validação da resposta é por regras (números, nomes, expressões proibidas): ela barra os casos previstos, mas uma
  frase enganosa sem número nem palavra proibida pode passar. Não foi testado com uma chave real neste projeto.
- A API pública da Deriv derruba a conexão a cada ~2 minutos; o servidor reconecta e preenche o buraco, mas
  durante a reconexão os dados ficam alguns segundos atrasados.
- Notificações do navegador dependem da permissão e do modo "Não perturbe" do sistema.
- A marca (logo) é original; "Lightweight Charts" é marca da TradingView, usada conforme a licença (atribuição
  mantida no gráfico).

## Endpoint

API pública da Deriv: `wss://api.derivws.com/trading/v1/options/ws/public` (sem token, máx. ~900 velas por
resposta; o download pagina sozinho). Para trocar, defina `DERIV_WS_URL`.
