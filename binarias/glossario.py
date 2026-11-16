"""Modo educativo: glossário curto (2 frases simples + 1 exemplo por termo) e o mini-tour do silêncio.

Textos próprios do Farol, sem promessa. Servidos em /api/glossario e conferidos por teste automático.
"""

from .config import MIN_OPERACOES, PAYOUT_PADRAO
from .estatistica import break_even

_BE = f"{100 * break_even(PAYOUT_PADRAO):.2f}".replace(".", ",")
_PAY = f"{100 * PAYOUT_PADRAO:.0f}"

GLOSSARIO = [
    {
        "termo": "Break-even",
        "texto": "É a taxa de acerto mínima para não perder dinheiro com um certo payout. "
        "Abaixo dela, quanto mais você opera, mais perde.",
        "exemplo": f"Com payout de {_PAY}%, o break-even é {_BE}%: acertar 52% ainda dá prejuízo.",
    },
    {
        "termo": "Payout",
        "texto": "É quanto a corretora paga sobre o valor da entrada quando você acerta. "
        "Quando erra, você perde o valor inteiro da entrada.",
        "exemplo": f"Entrada de R$ 10 com payout de {_PAY}%: acerto = +R$ 8,50; erro = −R$ 10.",
    },
    {
        "termo": "Intervalo de confiança",
        "texto": "É a margem de erro da taxa de acerto medida no passado. "
        "Com poucas operações a faixa é larga; com muitas, fica estreita.",
        "exemplo": "60% em 50 operações pode ser algo entre 46% e 72%: pode até estar abaixo do break-even.",
    },
    {
        "termo": "Intervalo de Wilson",
        "texto": "É a fórmula que o Farol usa para calcular a margem de erro de uma taxa de acerto. "
        "Ela funciona bem mesmo com poucas operações ou taxas perto de 0% e 100%.",
        "exemplo": "O Farol só aceita uma estratégia se a ponta de baixo da faixa de Wilson passar do break-even.",
    },
    {
        "termo": "Amostra mínima",
        "texto": f"É o número mínimo de operações ({MIN_OPERACOES}) para o Farol levar uma estratégia a sério. "
        "Poucas operações enganam: a sorte pesa muito.",
        "exemplo": "Ganhar 8 de 10 parece ótimo, mas é comum acontecer por puro acaso.",
    },
    {
        "termo": "Testes múltiplos (Holm)",
        "texto": "Quando muitas estratégias são testadas ao mesmo tempo, alguma pode parecer boa só por sorte. "
        "A correção de Holm fica mais exigente quanto mais estratégias são testadas.",
        "exemplo": "Jogando 20 moedas, é fácil uma dar 7 caras em 10; isso não quer dizer que ela é viciada.",
    },
    {
        "termo": "Walk-forward",
        "texto": "É escolher os parâmetros só com dados antigos e conferir o resultado em dados que ficaram de fora. "
        "Mostra se a estratégia funciona fora do período em que foi ajustada.",
        "exemplo": "Ajusta nos primeiros 70% do histórico e mede nos 30% finais, nunca vistos na escolha.",
    },
    {
        "termo": "Backtest",
        "texto": "É simular a estratégia no histórico, vela por vela, como se fosse ao vivo. "
        "Resultado bom no passado não garante resultado no futuro.",
        "exemplo": "Sinal no fechamento da vela, entrada na abertura da próxima, resultado na expiração.",
    },
    {
        "termo": "Média móvel",
        "texto": "É a média dos fechamentos das últimas N velas, que suaviza o sobe e desce. "
        "Preço acima de uma média longa costuma indicar tendência de alta.",
        "exemplo": "A média de 50 velas mostra a direção geral; a de 5 reage rápido.",
    },
    {
        "termo": "RSI",
        "texto": "Mede de 0 a 100 a força das subidas contra as quedas recentes. "
        "Perto de 70 o preço subiu muito rápido; perto de 30, caiu muito rápido.",
        "exemplo": "RSI em 25 mostra uma queda forte recente; não é previsão de alta.",
    },
    {
        "termo": "ADX",
        "texto": "Mede a força da tendência, sem dizer a direção. "
        "Valores altos indicam tendência firme; baixos, mercado sem direção.",
        "exemplo": "No Farol, ADX acima de 25 é tendência forte e abaixo de 20, fraca.",
    },
    {
        "termo": "ATR",
        "texto": "É o tamanho médio das velas recentes, considerando os saltos entre uma vela e outra. "
        "Serve para saber o que é um movimento grande ou pequeno naquele ativo.",
        "exemplo": "Se o ATR é 10 pontos, andar 30 pontos em uma vela é um movimento grande.",
    },
    {
        "termo": "MACD",
        "texto": "É a diferença entre uma média rápida e uma lenta, que mostra o impulso do preço. "
        "A linha de sinal é a média do próprio MACD; os cruzamentos marcam mudanças de impulso.",
        "exemplo": "MACD cruzando a linha de sinal para cima = o impulso de curto prazo virou para cima.",
    },
    {
        "termo": "Estocástico",
        "texto": "Mostra de 0 a 100 onde o fechamento está dentro da faixa máxima–mínima recente. "
        "Perto de 0 fechou no fundo da faixa; perto de 100, no topo.",
        "exemplo": "%K em 10 = fechou perto da mínima das últimas 14 velas.",
    },
    {
        "termo": "CCI",
        "texto": "Mede o quanto o preço se afastou da sua média, comparado ao afastamento normal. "
        "Acima de +100 ou abaixo de −100 é um afastamento grande.",
        "exemplo": "CCI em −180 = o preço está bem abaixo da média recente.",
    },
    {
        "termo": "Williams %R",
        "texto": "É parecido com o Estocástico, mas vai de −100 a 0. "
        "Perto de −100 o fechamento está no fundo da faixa recente.",
        "exemplo": "%R em −90 = fechou perto da mínima das últimas 14 velas.",
    },
    {
        "termo": "Bandas de Bollinger",
        "texto": "São duas linhas a alguns desvios-padrão acima e abaixo de uma média. "
        "Fechar fora das bandas é raro e indica movimento esticado.",
        "exemplo": "Bandas de 2 desvios: o preço costuma ficar dentro delas na maior parte do tempo.",
    },
    {
        "termo": "Canal de Keltner",
        "texto": "É uma faixa em volta de uma média, com largura medida em ATR. "
        "Mostra a oscilação normal; fechar fora dela é um movimento forte.",
        "exemplo": "Média de 20 velas ± 2 ATR.",
    },
    {
        "termo": "Canal de Donchian",
        "texto": "É a faixa entre a máxima e a mínima das últimas N velas. "
        "Um canal estreito indica mercado parado; rompê-lo indica saída da calmaria.",
        "exemplo": "Donchian de 20: máxima e mínima das últimas 20 velas.",
    },
    {
        "termo": "SuperTrend",
        "texto": "É uma linha que fica abaixo do preço na alta e acima na baixa, com distância medida em ATR. "
        "Ela muda de lado quando o preço a atravessa.",
        "exemplo": "SuperTrend abaixo do preço = leitura de alta naquele momento.",
    },
    {
        "termo": "Expiração",
        "texto": "É quantas velas a operação dura até o resultado. "
        "O Farol compara o preço de entrada com o fechamento da última vela da expiração.",
        "exemplo": "Expiração de 1 vela em M5 = a operação dura 5 minutos.",
    },
    {
        "termo": "Martingale",
        "texto": "É dobrar a entrada depois de cada perda para recuperar tudo de uma vez. "
        "Esconde o risco: uma sequência ruim pode levar a banca inteira, e o Farol não usa.",
        "exemplo": "R$ 10, R$ 20, R$ 40, R$ 80: quatro perdas seguidas já custam R$ 150.",
    },
    {
        "termo": "Ruína",
        "texto": "É perder uma parte tão grande da banca que fica difícil continuar. "
        "Quanto maior o % por operação, maior a chance de ruína.",
        "exemplo": "Com 10% por operação, 5 perdas seguidas levam quase metade da banca.",
    },
    {
        "termo": "Estratégia líder",
        "texto": "É a estratégia com vantagem comprovada no topo do ranking; só ela gera aviso de entrada. "
        "A troca de líder exige confirmação, para não mudar a cada vela.",
        "exemplo": "Sem nenhuma estratégia comprovada, não há líder e o Farol fica em silêncio.",
    },
    {
        "termo": "Progresso de formação",
        "texto": "Mostra de 0 a 100% o quanto as condições da líder já estão cumpridas na vela atual. "
        "Não é chance de acerto: 100% só quer dizer que o sinal sairia se a vela fechasse agora.",
        "exemplo": "2 de 3 condições cumpridas e o preço perto do gatilho = progresso alto.",
    },
]

SILENCIO = [
    {
        "titulo": "Silêncio é uma resposta",
        "texto": "O Farol só avisa quando os números mostram vantagem. Na maior parte do tempo, não mostram: "
        "ficar em silêncio é o comportamento esperado, não um defeito.",
    },
    {
        "titulo": "Poucas operações",
        "texto": f"Com menos de {MIN_OPERACOES} operações na janela recente, a sorte pesa demais. "
        "A estratégia vai para 'abaixo do mínimo' ou 'poucos dados'.",
    },
    {
        "titulo": "Margem de erro encosta no break-even",
        "texto": "Mesmo com acerto bonito, se a ponta de baixo da margem de erro não passa do break-even, "
        "pode não haver vantagem real. Sem sinal.",
    },
    {
        "titulo": "Muitas estratégias, muita sorte possível",
        "texto": "O Farol testa várias estratégias ao mesmo tempo e corrige isso (Holm). "
        "Uma que passou 'por pouco' pode ser só sorte e é descartada.",
    },
    {
        "titulo": "A líder não deu sinal",
        "texto": "Ter uma líder não basta: ela precisa cumprir todas as condições na vela. "
        "Enquanto isso, a tela mostra AGUARDAR ou SE PREPARANDO.",
    },
    {
        "titulo": "Conflito",
        "texto": "Se outra estratégia relevante aponta o lado oposto, o Farol mostra CONFLITO e não avisa entrada.",
    },
    {
        "titulo": "Limite do dia",
        "texto": "Se você atingiu o limite de perda ou de losses seguidos em 'Minha banca', os avisos de entrada "
        "são silenciados até o dia seguinte.",
    },
]
