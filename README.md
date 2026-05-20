# Prueba_Scrapling

Scrapers de artículos sobre autopartes usando [Scrapling](https://github.com/D4Vinci/Scrapling). Extrae noticias de **La Nacion** y **Mundo Aftermarket** y las guarda directamente en MongoDB Atlas.

## Fuentes

| Spider | Sitio | Colección en MongoDB |
|---|---|---|
| `LanacionSpider` | lanacion.com.ar — búsqueda "autopartes" | `autopartes` |
| `AftermarketSpider` | mundoaftermarket.com/mercado | `aftermarket` |

---

## Opción A — Docker (recomendado)

No necesitás instalar Python, Node ni ninguna dependencia. Solo Docker.

### Requisitos

- [Docker Desktop](https://docs.docker.com/get-docker/) (incluye Docker Compose)

### 1. Clonar el repositorio

```bash
git clone https://github.com/Manuel-Gartenkrot-Casal/Prueba_Scrapling.git
cd Prueba_Scrapling
```

### 2. Levantar todo

```bash
docker compose up --build
```

La primera build tarda varios minutos porque descarga e instala Chromium dentro del contenedor Python. Las siguientes veces es instantáneo.

### 3. Abrir el dashboard

```
http://localhost:3000
```

Desde ahí podés correr cada spider con un botón. Los resultados se guardan directo en MongoDB.

### Detener los contenedores

```bash
docker compose down
```

### Arquitectura

```
[Browser] → botón → [Express/TypeScript :3000] → HTTP → [Flask/Python :5000] → spiders → MongoDB Atlas
```

---

## Opción B — Sin Docker (desarrollo local)

### Requisitos

- Python 3.10+
- Node.js 20+

### 1. Clonar el repositorio

```bash
git clone https://github.com/Manuel-Gartenkrot-Casal/Prueba_Scrapling.git
cd Prueba_Scrapling
```

### 2. Instalar dependencias Python

```bash
pip install scrapling "scrapling[fetchers]" "pymongo[srv]" flask
```

### 3. Instalar browsers para scraping dinámico

```bash
python -c "from scrapling.cli import install; install([], standalone_mode=False)"
```

### 4. Instalar dependencias Node y compilar TypeScript

```bash
cd express
npm install
npm run build
cd ..
```

### 5. Levantar el servicio Python (terminal 1)

```bash
python flask_api.py
```

### 6. Levantar el servidor Express (terminal 2)

```bash
cd express
SCRAPERS_URL=http://localhost:5000 node dist/index.js
```

Luego abrí **http://localhost:3000**

### Correr los spiders directamente (sin dashboard)

```bash
python runlanacion.py
python runaftermarket.py
```

### Migrar JSON existentes a MongoDB (solo una vez)

Si tenés archivos previos en `data/`:

```bash
python seed_db.py
```

---

## Base de datos

Los datos se guardan en **MongoDB Atlas** en la base `PruebaScrapling`:

- `autopartes` → artículos de La Nacion
- `aftermarket` → artículos de Mundo Aftermarket

La conexión está configurada en `db.py`. Los artículos no se duplican: se usa la URL como clave única.

---

## Agregar un spider nuevo

1. Crear `spiders/nuevo_spider.py`
2. Crear `runnuevo.py`
3. En `flask_api.py` agregar a `SPIDERS`: `"nombre": "runnuevo.py"`
4. En `express/src/index.ts` agregar `"nombre"` al array `VALID_SPIDERS`
5. En `express/src/public/index.html` copiar una card y cambiar el nombre
6. Si usás Docker: `docker compose up --build`
