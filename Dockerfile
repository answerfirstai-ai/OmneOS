FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JARVIS_ENVIRONMENT=production \
    JARVIS_HOST=0.0.0.0 \
    JARVIS_PORT=8787

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin jarvis

COPY pyproject.toml README.md LICENSE ./
COPY core ./core
COPY configs ./configs

RUN pip install --no-cache-dir . \
    && mkdir -p /app/workspace /app/memory \
    && chown -R jarvis:jarvis /app

USER jarvis

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health')"

CMD ["jarvis", "serve"]
