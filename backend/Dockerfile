# EletroGestor API -- imagem de producao.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Roda como usuario sem privilegios.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# As migrations rodam no "pre-deploy"/release (ver render.yaml), nao a cada boot.
# --forwarded-allow-ips: confia nos cabecalhos do proxy da plataforma (Render/Cloudflare).
CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY:-2} -b 0.0.0.0:${PORT:-8000} --forwarded-allow-ips='*' --access-logfile - --timeout 60"]
