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

Desde ahí podés:

- Correr cada spider individualmente con su botón.
- **⚡ Scrapear todos los artículos** — corre las 5 fuentes de una sola vez.
- **✨ Generar artículos con IA** — reescribe lo scrapeado con la IA y muestra el resultado en el Output.

Los resultados se guardan directo en MongoDB.

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

### Correr una fuente directamente (sin dashboard)

Todas las fuentes usan el mismo runner genérico; le pasás el nombre de la fuente
(el campo `nombre` de `fuentes.json`):

```bash
python run_fuente.py lanacion
python run_fuente.py aftermarket
python run_fuente.py ambito
python run_fuente.py cenital
python run_fuente.py perfil
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

## Agregar una fuente nueva

Ya no hace falta tocar código ni crear spiders. Toda la configuración vive en
**`fuentes.json`**: agregás una entrada nueva y listo. El spider genérico, el
runner, Flask, el dashboard y el generador la toman automáticamente.

Agregá un objeto al array de `fuentes.json`:

```json
{
  "nombre": "miFuente",
  "etiqueta": "Mi Fuente",
  "coleccion": "mifuente",
  "start_url": "https://sitio.com/buscador?q=autopartes",
  "base": "https://sitio.com",
  "modo": "articulos",
  "max_articulos": 3,
  "min_parrafo": 40,
  "selectores": {
    "item": "article",
    "link": "a::attr(href)",
    "titulo": ["h2::text"],
    "fecha": ["time::attr(datetime)", "time::text"],
    "cuerpo": "p"
  },
  "basura": ["Suscribite", "Newsletter"]
}
```

Campos:

| Campo | Qué es |
|---|---|
| `nombre` | identificador interno (sin espacios), se usa en la URL y los IDs |
| `etiqueta` | nombre lindo que se muestra en el dashboard |
| `coleccion` | colección de MongoDB donde se guardan los artículos |
| `start_url` | página de listado/búsqueda desde donde arranca |
| `base` | dominio base, para completar links relativos |
| `modo` | `"articulos"` (recorre bloques `<article>`) o `"links"` (junta href sueltos) |
| `max_articulos` | tope de notas a scrapear |
| `min_parrafo` | largo mínimo de un `<p>` para contar como cuerpo |
| `selectores.item` | (modo articulos) selector del bloque contenedor de cada nota |
| `selectores.link` | selector del link a la nota |
| `selectores.titulo` | uno o varios selectores del título (se prueba en orden) |
| `selectores.fecha` | (opcional) selectores de fecha en la página de la nota |
| `selectores.bajada` | (opcional) selector de bajada/copete |
| `selectores.cuerpo` | selector de los párrafos (default `p`) |
| `basura` | frases a excluir del cuerpo (menús, muros de pago, etc.) |

En modo `"links"` podés además usar `link_fallback` y `link_fallback_contiene`
para cuando el selector principal no encuentra resultados.

Si usás Docker, reconstruí: `docker compose up --build`.
