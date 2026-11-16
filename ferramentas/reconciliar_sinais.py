"""Converte o resultados/sinais_ao_vivo.csv para o formato novo e resolve os sinais PENDENTE
(inclusive os CANCELADOS da versão antiga) com as velas históricas da Deriv.

    python ferramentas/reconciliar_sinais.py

Faz uma cópia do CSV em backups/ ANTES de qualquer mudança. Nenhuma linha é apagada: o que a Deriv não tiver
mais vira CANCELADO com o motivo; o que foi resolvido fica marcado "resolvido na reconciliação".
"""

import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binarias.deriv import DerivClient
from binarias.log import configurar_log
from binarias.registro import CSV_SINAIS, MOTIVO_ANTIGO, TEXTO_RECONCILIADO, Registro, reconciliar


async def principal() -> None:
    configurar_log()
    reg = Registro(CSV_SINAIS)
    copia = reg.backup("_antes_da_reconciliacao")
    print(f"Cópia de segurança: {copia}")
    antes = reg.ler()  # converte o formato antigo, se preciso (com outra cópia em backups/)
    reabertas = {l["id"] for l in antes if l["motivo"] == MOTIVO_ANTIGO and l["resultado"] == "PENDENTE"}
    print(f"Linhas: {len(antes)} | antes: {dict(Counter(l['resultado'] for l in antes))}")
    async with DerivClient() as cli:
        await cli.tempo_servidor()
        resumo = await reconciliar(reg, cli.pedir, cli.agora())
    depois = reg.ler()
    print(f"Reconciliação: {resumo}")
    print(f"Linhas: {len(depois)} | depois: {dict(Counter(l['resultado'] for l in depois))}")
    das_antigas = Counter(l["resultado"] for l in depois if l["id"] in reabertas)
    resolvidas = sum(n for k, n in das_antigas.items() if k in ("WIN", "LOSS", "EMPATE"))
    print(f"Canceladas da versão antiga: {len(reabertas)} -> resolvidas {resolvidas} ({dict(das_antigas)})")
    print(f"Marcadas como '{TEXTO_RECONCILIADO}': {sum(l['motivo'] == TEXTO_RECONCILIADO for l in depois)}")
    assert len(depois) == len(antes), "nenhuma linha pode sumir"


if __name__ == "__main__":
    asyncio.run(principal())
