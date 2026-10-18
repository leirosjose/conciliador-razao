# Imagem do app: so a tela (upload de razao .xls/.xlsx). Sem banco, sem JDK, sem driver.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# dependencias primeiro: a camada so refaz quando o requirements muda
# (requirements.txt = so o runtime; pytest/xlwt/playwright ficam no requirements-dev.txt)
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY .streamlit/ .streamlit/
COPY core/ core/
COPY parser/ parser/
COPY relatorio/ relatorio/
COPY app/ app/

# nao-root; o app nao escreve em /app (registro vai pro stderr, temporario pro /tmp)
RUN useradd --create-home --uid 10001 conciliador
USER conciliador

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"

# 0.0.0.0 DENTRO do container; quem limita ao 127.0.0.1 do host e o compose
CMD ["streamlit", "run", "app/main.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
