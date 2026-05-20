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

## Generación de artículos con IA

Lee los artículos scrapeados de MongoDB y genera un artículo periodístico nuevo usando **Gemini**.

### Configuración

1. Obtené una API key en [Google AI Studio](https://aistudio.google.com/app/apikey)
2. En `generar_articulo.py`, reemplazá `"TU_API_KEY"` con tu clave:
   ```python
   GEMINI_API_KEY = "tu-clave-aqui"
   ```

### Instalación (si corrés sin Docker)

```bash
pip install google-generativeai
```

### Uso

```bash
# Genera un artículo combinando ambas fuentes (3 docs c/u)
python generar_articulo.py

# Solo artículos de La Nacion
python generar_articulo.py --fuente lanacion

# Solo artículos de Aftermarket
python generar_articulo.py --fuente aftermarket

# Usar más documentos como base
python generar_articulo.py --cantidad 5
```

El artículo generado se imprime en consola y se guarda automáticamente en la colección `articulos_generados` de MongoDB. Cada documento fuente se marca como `usado_para_articulo: true` para no repetirlo.
