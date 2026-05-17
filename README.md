# Prueba_Scrapling

Scrapers de artículos sobre autopartes usando [Scrapling](https://github.com/D4Vinci/Scrapling). Extrae noticias de **La Nacion** y **Mundo Aftermarket** y las guarda directamente en una base de datos MongoDB Atlas.

## Fuentes

| Spider | Sitio | Colección en MongoDB |
|---|---|---|
| `LanacionSpider` | lanacion.com.ar — búsqueda "autopartes" | `autopartes` |
| `AftermarketSpider` | mundoaftermarket.com/mercado | `aftermarket` |

---

## Instalación desde cero

### 1. Clonar el repositorio

```bash
git clone https://github.com/Manuel-Gartenkrot-Casal/Prueba_Scrapling.git
cd Prueba_Scrapling
```

### 2. Instalar dependencias

```bash
pip install scrapling
pip install "scrapling[fetchers]"
pip install "pymongo[srv]"
```

### 3. Instalar browsers para scraping dinámico

```bash
python -c "from scrapling.cli import install; install([], standalone_mode=False)"
```

---

## Uso

### Correr el spider de La Nacion

```bash
python runlanacion.py
```

### Correr el spider de Mundo Aftermarket

```bash
python runaftermarket.py
```

Cada ejecución scrapea y guarda los artículos directamente en MongoDB. Los artículos ya existentes se actualizan sin generar duplicados (se usa la URL como clave única).

---

## Migración de datos existentes (solo una vez)

Si tenés archivos JSON previos en la carpeta `data/`, podés importarlos a MongoDB con:

```bash
python seed_db.py
```

---

## Base de datos

Los datos se guardan en **MongoDB Atlas** en la base `PruebaScrapling`, con dos colecciones:

- `autopartes` → artículos de La Nacion
- `aftermarket` → artículos de Mundo Aftermarket

La configuración de conexión está en `db.py`.

---

## Docker + Dashboard web

La branch `docker-typescript` incluye toda la infraestructura dockerizada y un dashboard web para correr los spiders con un botón.

### Arquitectura

```
[Browser] → botón → [Express/TypeScript :3000] → HTTP → [Flask/Python :5000] → spiders → MongoDB Atlas
```

### Requisitos

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/) (incluido en Docker Desktop)

### Levantar todo

```bash
docker compose up --build
```

La primera vez tarda varios minutos porque descarga e instala Chromium dentro del contenedor Python.

Luego abrí el dashboard en **http://localhost:3000**

### Detener

```bash
docker compose down
```

### Agregar un spider nuevo

1. Crear `spiders/nuevo_spider.py`
2. Crear `runnuevo.py`
3. En `flask_api.py`, agregar a `SPIDERS`: `"nombre": "runnuevo.py"`
4. En `express/src/index.ts`, agregar `"nombre"` al array `VALID_SPIDERS`
5. En `express/src/public/index.html`, copiar una card y cambiar el nombre

