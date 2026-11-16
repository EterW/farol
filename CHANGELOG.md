# Changelog

## 1.1.0 — 2026-11-16

### Adicionado
- **Indicadores** (causais, testados truncando o futuro): EMA, MACD, Estocástico, Williams %R, CCI, Keltner,
  Donchian, SuperTrend e VWAP (só com volume; a Deriv não fornece, então não é usado).
- **9 estratégias candidatas**: MACD cruzamento, MACD + tendência, Estocástico reversão, SuperTrend + recuo,
  Keltner reversão, Keltner rompimento, Donchian após compressão, CCI reversão, Williams %R + tendência. Cada uma
  com condições, grade de parâmetros, sigla, ícone SVG (`static/icones/`) e explicação leiga. Total: 20.
- **Correção de testes múltiplos**: p-valor binomial exato + Bonferroni, Holm e Benjamini-Hochberg (FDR).
  Laboratório (`validar.py`) exige Holm para "passar" e reporta hipóteses e combinações testadas.
- **Assistente "Explique para mim"** (opcional, desligado sem `ANTHROPIC_API_KEY`): explica, não prevê;
  resposta validada no código; cache por vela, limite por hora, tempo limite, modelo configurável.
- **Minha banca**: entrada sugerida, perda máxima do dia, parar após N losses, meta, bloqueio "pare por hoje"
  (silencia avisos de entrada no servidor), simulador "e se" (Monte Carlo, sem martingale), diário com CSV e
  curva da banca.
- **Modo educativo**: glossário (25 termos), tour "Por que o Farol fica em silêncio", página `/como-decide`.
- Screenshots dos cartões novos em `tests/telas.py`.

### Alterado
- **Ranking ao vivo mais exigente**: além de ≥ 100 operações e IC de Wilson acima do break-even, a vantagem
  passa a exigir p ajustado por Holm < 2,5% entre todas as estratégias testadas.
- Banca e assistente ficam lado a lado embaixo do gráfico; veredito esmaecido quando o limite do dia é atingido.

### Corrigido
- `ruff` e `mypy` limpos em todo o repositório (inclui avisos antigos em testes e em `sessao.py`).
- BOM no `.gitattributes` que fazia o git ignorar a primeira linha.

### Laboratório
- 16/11/2026: 20 estratégias × 4 pares (80 hipóteses), 360 combinações no treino: **nenhuma passou**
  (0/80 com vantagem no teste, mesmo sem correção).

## 1.0.0 — 2026-11-12
- Farol: backtest, ranking com Wilson e break-even, líder com histerese, avisos decididos no servidor,
  validação walk-forward, modo ao vivo e marca própria.
