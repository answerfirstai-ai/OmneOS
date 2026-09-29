FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMNE_ENVIRONMENT=production \
    OMNE_HOST=0.0.0.0 \
    OMNE_PORT=8787

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin OMNE

COPY pyproject.toml README.md LICENSE ./
COPY core ./core
COPY configs ./configs

RUN pip install --no-cache-dir . \
    && mkdir -p /app/workspace /app/memory \
    && chown -R OMNE:OMNE /app

USER OMNE

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health')"

CMD ["OMNE", "serve"]
