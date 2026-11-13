"""Registro de erros em resultados/erros.log (rotativo) e no console."""
import logging
from logging.handlers import RotatingFileHandler

from .config import ARQUIVO_LOG, garantir_pastas

_FORMATO = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


def configurar_log(nivel_console: int = logging.WARNING) -> logging.Logger:
    """Chamado pelos pontos de entrada (main.py, live.py, validar.py). Idempotente."""
    raiz = logging.getLogger("binarias")
    if getattr(raiz, "_configurado", False):
        return raiz
    garantir_pastas()
    raiz.setLevel(logging.INFO)
    arquivo = RotatingFileHandler(ARQUIVO_LOG, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    arquivo.setLevel(logging.WARNING)
    arquivo.setFormatter(logging.Formatter(_FORMATO))
    console = logging.StreamHandler()
    console.setLevel(nivel_console)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    raiz.addHandler(arquivo)
    raiz.addHandler(console)
    raiz._configurado = True
    return raiz


def obter(nome: str) -> logging.Logger:
    return logging.getLogger(f"binarias.{nome}")
