"""Modo ao vivo: site local com gráfico, ranking, análise de mercado, Top 3 e sinal único.

Uso:
    python live.py                 -> abre http://127.0.0.1:8000 no navegador
    python live.py --porta 8080 --sem-navegador
"""
from binarias.servidor import app, main  # noqa: F401  (app exposto para "uvicorn live:app")

if __name__ == "__main__":
    main()
