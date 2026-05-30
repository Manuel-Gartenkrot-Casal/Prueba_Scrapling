# Prueba_Scrapling

Scrapers de artículos sobre autopartes usando [Scrapling](https://github.com/D4Vinci/Scrapling) + generador de artículos periodísticos con IA. Extrae noticias de cinco fuentes, las guarda en MongoDB Atlas y opcionalmente genera un artículo nuevo combinando el contenido scrapeado.

## Fuentes

| Spider | Sitio | Colección en MongoDB |
|---|---|---|
| `LanacionSpider` | lanacion.com.ar — búsqueda "autopartes" | `autopartes` |
| `AftermarketSpider` | mundoaftermarket.com/mercado | `aftermarket` |
| `AmbitoSpider` | ambito.com — sección industria automotriz | `ambito` |
| `CenitalSpider` | cenital.com — búsqueda "autopartes" | `cenital` |
| `PerfilSpider` | perfil.com — búsqueda "autopartes" | `perfil` |

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
pip install scrapling "scrapling[fetchers]" "pymongo[srv]" flask python-dotenv requests
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
python runambito.py
python runcenital.py
python runperfil.py
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
- `ambito` → artículos de Ambito Financiero
- `cenital` → artículos de Cenital
- `perfil` → artículos de Perfil
- `articulos_generados` → artículos generados por IA

La conexión está configurada en `db.py`. Los artículos no se duplican: se usa la URL como clave única.

---

## Generación de artículos con IA

Lee los artículos scrapeados de MongoDB y genera un artículo periodístico usando la API de **NVIDIA** (modelo `google/gemma-3n-e4b-it`). El artículo generado se guarda en la colección `articulos_generados`.

### Configuración

Creá un archivo `.env` en la raíz del proyecto con tu API key de NVIDIA:

```
NVIDIA_API_KEY=tu_clave_aqui
```

Podés conseguir una clave gratuita en [build.nvidia.com](https://build.nvidia.com).

### Uso

```bash
# Genera un artículo combinando las 5 fuentes (3 docs c/u)
python generar_articulo.py

# Solo una fuente
python generar_articulo.py --fuente lanacion
python generar_articulo.py --fuente aftermarket
python generar_articulo.py --fuente ambito
python generar_articulo.py --fuente cenital
python generar_articulo.py --fuente perfil

# Combinar fuentes específicas
python generar_articulo.py --fuente lanacion ambito perfil

# Usar más documentos como base
python generar_articulo.py --cantidad 5
```

El artículo se imprime en consola y se guarda en la colección `articulos_generados`. Cada documento fuente se marca como `usado_para_articulo: true` para no repetirlo en generaciones futuras.

---

## Agregar un spider nuevo

1. Crear `spiders/nuevo_spider.py`
2. Crear `runnuevo.py`
3. En `flask_api.py` agregar a `SPIDERS`: `"nombre": "runnuevo.py"`
4. En `express/src/index.ts` agregar `"nombre"` al array `VALID_SPIDERS`
5. En `express/src/public/index.html` copiar una card y cambiar el nombre
6. En `db.py` agregar la colección: `col_nuevo = db["nuevo"]`
7. En `generar_articulo.py` agregar a `FUENTES`: `"nombre": db["nuevo"]`
8. Si usás Docker: `docker compose up --build`
