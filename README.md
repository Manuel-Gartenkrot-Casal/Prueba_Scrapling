# AfterDrive Intelligence — Scrapling + IA

Sistema de scraping automatizado de noticias del sector automotriz y postventa, con generador de artículos periodísticos por IA (RAG + embeddings).

Extrae artículos de múltiples fuentes, los guarda en MongoDB Atlas y genera contenido original combinando el material scrapeado con un pipeline semántico (KNN + text search).

---

## Arquitectura

```
Browser → Express :3000 → Flask :5000 → Scrapling spiders → MongoDB Atlas
                                      → LM Studio / NVIDIA (IA)
```

| Componente | Tecnología | Puerto |
|---|---|---|
| Frontend (dashboard) | HTML/CSS/JS estático | 3000 |
| API proxy | Express + TypeScript | 3000 |
| API principal | Flask + Python | 5000 |
| Scraping | Scrapling (StealthyFetcher) | — |
| IA local | LM Studio (mistral-7b) | 1234 |
| IA cloud | NVIDIA Build (GLM-5.2) | — |
| Base de datos | MongoDB Atlas | — |

---

## Requisitos

| Opción | Python | Node.js | Docker |
|---|---|---|---|
| Docker (recomendado) | No | No | Sí |
| Local | 3.10+ | 20+ | No |

---

## Opción A — Docker (recomendado)

No necesitás instalar nada más que Docker Desktop.

### 1. Clonar

```bash
git clone https://github.com/Manuel-Gartenkrot-Casal/Prueba_Scrapling.git
cd Prueba_Scrapling
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Abrí `.env` y completá al menos `MONGO_URI`. Elegí el proveedor de IA:

```env
# Para NVIDIA (cloud, funciona sin nada local):
AI_PROVIDER=nvidia
NVIDIA_API_KEY=tu-api-key-aqui

# O para LM Studio (local, necesitás LM Studio corriendo):
AI_PROVIDER=local
```

### 3. Levantar

```bash
docker compose up --build
```

La primera vez tarda ~5-8 minutos (descarga Chromium + instala dependencias). Las siguientes es inmediato.

### 4. Abrir

```
http://localhost:3000
```

### 5. Detener

```bash
docker compose down
```

---

## Opción B — Local (desarrollo)

### 1. Clonar

```bash
git clone https://github.com/Manuel-Gartenkrot-Casal/Prueba_Scrapling.git
cd Prueba_Scrapling
```

### 2. Configurar entorno

```bash
cp .env.example .env
```

Editá `.env` con tus credenciales (ver [Configuración](#configuración) más abajo).

### 3. Python — dependencias

```bash
pip install -r requirements.txt
```

### 4. Python — navegador para scraping

```bash
python -c "from scrapling.cli import install; install([], standalone_mode=False)"
```

### 5. Node.js — compilar Express

```bash
cd express
npm install
npm run build
cd ..
```

### 6. Levantar Flask (terminal 1)

```bash
python flask_api.py
```

### 7. Levantar Express (terminal 2)

```bash
cd express
node dist/index.js
```

### 8. Abrir

```
http://localhost:3000
```

---

## Configuración (.env)

| Variable | Requerido | Descripción |
|---|---|---|
| `MONGO_URI` | Sí | URI de conexión a MongoDB Atlas |
| `AI_PROVIDER` | Sí | `local` o `nvidia` |
| `NVIDIA_API_KEY` | Si nvidia | API key de NVIDIA Build |
| `LMSTUDIO_URL` | Si local | URL de LM Studio (default: `http://localhost:1234/v1`) |
| `LMSTUDIO_MODEL` | Si local | Modelo a usar (default: `mistral-7b-instruct-v0.3`) |

---

## Dashboard

El frontend en `http://localhost:3000` ofrece:

- **Scraping manual** — ejecutá cada fuente individualmente o todas juntas
- **Generador de artículos** — elegí tema, personalidad (divulgativo/técnico/negocios) y generá
- **Pipeline visual** — HUD animado que muestra el progreso del scraping
- **Descubrimiento de fuentes** — DuckDuckGo search para encontrar nuevos sitios del nicho
- **Configuración** — intervalo de ejecución, máximo de artículos por fuente
- **Selector de proveedor** — cambiar entre LM Studio y NVIDIA en un click
- **Logs en tiempo real** — consola con colores por tipo de evento

---

## Fuentes de scraping

| Fuente | Dominio | Colección MongoDB |
|---|---|---|
| La Nación | lanacion.com.ar | `autopartes` |
| Mundo Aftermarket | mundoaftermarket.com | `aftermarket` |
| Ambito Financiero | ambito.com | `ambito` |
| Cenital | cenital.com | `cenital` |
| Perfil | perfil.com | `perfil` |

Las fuentes se configuran en `scraper.py`. Cada spider busca "autopartes" y related terms en su sitio.

---

## Generación de artículos con IA

Pipeline RAG híbrido:

1. **KNN** — selecciona semilla más novedosa (coseno entre embeddings) y encuentra vecinos semánticos
2. **Text search** — busca documentos relacionados por tema en MongoDB
3. **Merge** — combina ambos pools rankeando por `max(similitud_coseno, textScore)`
4. **Redacción** — IA escribe el artículo con contexto completo (~28K tokens)
5. **Dedup** — verifica que no se parezca a uno previo (coseno ≥ 0.85 = descarte)
6. **Post-procesamiento** — elimina secciones duplicadas, CTA repetido, errores gramaticales conocidos

### Uso por CLI

```bash
python generar_articulo.py

# Filtrar por fuentes
python generar_articulo.py --fuente lanacion aftermarket

# Generar con tema específico
python generar_articulo.py --tema "tendencias del aftermarket 2026"
```

### Backfill de embeddings

Si hay artículos previos al sistema de embeddings:

```bash
python embeddings.py
```

---

## Base de datos (MongoDB Atlas)

Base: `PruebaScrapling`

| Colección | Contenido |
|---|---|
| `autopartes` | Artículos de La Nación |
| `aftermarket` | Artículos de Mundo Aftermarket |
| `ambito` | Artículos de Ambito Financiero |
| `cenital` | Artículos de Cenital |
| `perfil` | Artículos de Perfil |
| `articulos_generados` | Artículos generados por IA (con embeddings) |
| `trusted_urls` | URLs confiables para scraping automático |
| `suggested_urls` | URLs sugeridas por el descubridor de fuentes |
| `afterdrive` | Configuración del scheduler |

La URL se usa como clave única — no se duplican artículos.

---

## Agregar una fuente nueva

1. Crear `spiders/nuevo_spider.py`
2. Crear `runnuevo.py`
3. En `flask_api.py` agregar a `SPIDERS`: `"nuevo": "runnuevo.py"`
4. En `express/src/index.ts` agregar `"nuevo"` al array `VALID_SPIDERS`
5. En `express/src/public/index.html` copiar una card y cambiar el nombre
6. En `db.py` agregar la colección: `col_nuevo = db["nuevo"]`
7. En `generar_articulo.py` agregar a `FUENTES`: `"nuevo": db["nuevo"]`
8. Si usás Docker: `docker compose up --build`

---

## Estructura del proyecto

```
Prueba_Scrapling/
├── flask_api.py              # API principal (scraping, generación, health)
├── scraper.py                # Scrapling spiders (StealthyFetcher + fallback Wayback)
├── scheduler.py              # APScheduler para ejecución automática
├── generar_articulo.py       # Orquestador de generación RAG
├── lm_studio.py              # Prompts por personalidad + llamadas a IA
├── embeddings.py             # Cálculo de embeddings
├── db.py                     # Conexión MongoDB Atlas
├── discover_sources.py       # DuckDuckGo search para nuevas fuentes
├── add_url.py                # Alta de URLs manual
├── run_automation.py         # Runner del pipeline completo
├── requirements.txt          # Dependencias Python
├── Dockerfile                # Imagen Python (Flask + Scrapling)
├── docker-compose.yml        # Orquestación de servicios
├── .env.example              # Template de variables de entorno
└── express/
    ├── src/
    │   ├── index.ts          # Express proxy server
    │   └── public/
    │       └── index.html    # Dashboard completo (HTML/CSS/JS)
    ├── package.json
    ├── tsconfig.json
    └── Dockerfile            # Imagen Node.js (Express)
```
