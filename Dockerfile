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

# Copiar código fuente
COPY db.py .
COPY lm_studio.py .
COPY seed_db.py .
COPY flask_api.py .
COPY generar_articulo.py .
COPY runlanacion.py .
COPY runaftermarket.py .
COPY runambito.py .
COPY runcenital.py .
COPY runperfil.py .
COPY spiders/ ./spiders/
COPY .env .

EXPOSE 5000
CMD ["python", "flask_api.py"]
