FROM python:3.12-slim

WORKDIR /app

# Dependencias de sistema necesarias para Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --default-timeout=300 --no-cache-dir -r requirements.txt

# Instalar Chromium con sus dependencias de sistema (vía Playwright)
# y luego los browsers adicionales de Scrapling (camoufox)
RUN playwright install --with-deps chromium && \
    python -c "from scrapling.cli import install; install([], standalone_mode=False)"

# Crear usuario no-root
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Copiar código fuente
COPY db.py .
COPY lm_studio.py .
COPY embeddings.py .
COPY flask_api.py .
COPY generar_articulo.py .
COPY scraper.py .
COPY scheduler.py .
COPY add_url.py .
COPY discover_sources.py .

# Cambiar propiedad y usar usuario no-root
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD curl -f http://localhost:5000/health || exit 1

CMD ["python", "flask_api.py"]
