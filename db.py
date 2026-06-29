import datetime
import os
from pymongo import MongoClient, ReplaceOne, UpdateOne
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/PruebaScrapling")

client = MongoClient(MONGO_URI)
db = client["PruebaScrapling"]

col_lanacion    = db["autopartes"]    # artículos de La Nacion
col_aftermarket = db["aftermarket"]   # artículos de Mundo Aftermarket
col_ambito      = db["ambito"]        # artículos de Ambito Financiero
col_cenital     = db["cenital"]       # artículos de Cenital
col_perfil      = db["perfil"]        # artículos de Perfil
col_descartados = db["articulos_descartados"]
col_custom = db["custom"]

COLECCIONES_URLS = [col_lanacion, col_aftermarket, col_ambito, col_cenital, col_perfil, col_descartados, col_custom]

COLECCIONES_TEXTO = {
    col_lanacion:    [("titulo", "text"), ("cuerpo", "text")],
    col_aftermarket: [("titulo", "text"), ("bajada", "text"), ("cuerpo", "text")],
    col_ambito:      [("titulo", "text"), ("cuerpo", "text")],
    col_cenital:     [("titulo", "text"), ("cuerpo", "text")],
    col_perfil:      [("titulo", "text"), ("cuerpo", "text")],
    col_custom:      [("titulo", "text"), ("cuerpo", "text")],
}


def crear_indices_texto():
    for col, campos in COLECCIONES_TEXTO.items():
        try:
            col.create_index(campos, default_language="spanish", name="text_search", background=True)
        except Exception:
            pass
    try:
        col_generados = db["articulos_generados"]
        col_generados.create_index([("contenido", "text")], default_language="spanish", name="text_search", background=True)
    except Exception:
        pass


def guardar_items(items, coleccion):
    """
    Inserta una lista de dicts en la colección indicada.
    Usa ReplaceOne con upsert=True sobre 'url' para evitar duplicados.
    """
    if not items:
        return 0

    operaciones = [
        ReplaceOne({"url": item["url"]}, item, upsert=True)
        for item in items
    ]
    resultado = coleccion.bulk_write(operaciones)
    return resultado.upserted_count + resultado.modified_count


def clasificar_y_guardar(items, coleccion, clasificador_fn):
    """
    Clasifica cada item usando clasificador_fn y guarda solo los aprobados.
    Los rechazados se persisten en la colección 'articulos_descartados' para auditoría.

    clasificador_fn(titulo, cuerpo) -> {"aprobado": bool, "razon": str}
    Returns:
        {"total": int, "aprobados": int, "rechazados": int, "detalles": list[dict]}
    """
    if not items:
        return {"total": 0, "aprobados": 0, "rechazados": 0, "detalles": []}

    aprobados = []
    detalles = []

    for item in items:
        titulo = item.get("titulo", "(sin título)")
        cuerpo = item.get("cuerpo", item.get("bajada", ""))

        resultado = clasificador_fn(titulo, cuerpo)

        if resultado["aprobado"]:
            aprobados.append(item)
            detalles.append({"titulo": titulo, "estado": "aprobado"})
        else:
            col_descartados.replace_one(
                {"url": item.get("url", "")},
                {
                    "url":            item.get("url", ""),
                    "fecha_descarte": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
                upsert=True,
            )
            detalles.append({
                "titulo": titulo,
                "estado": "rechazado",
                "razon":  resultado.get("razon", ""),
            })

    if aprobados:
        # Vectorizar cada artículo aprobado para que nazca con su embedding.
        # Import diferido: embeddings.py importa db, así evitamos el ciclo.
        # Si LM Studio no responde, se guarda sin vector y el backfill lo agarra.
        from embeddings import texto_para_embedding
        from lm_studio import calcular_embedding
        for item in aprobados:
            vec = calcular_embedding(texto_para_embedding(item))
            if vec:
                item["embedding"] = vec

        operaciones = [
            UpdateOne(
                {"url": item["url"]},
                {"$set": item, "$setOnInsert": {"usado_para_articulo": False}},
                upsert=True
            )
            for item in aprobados
        ]
        coleccion.bulk_write(operaciones)

    return {
        "total":      len(items),
        "aprobados":  len(aprobados),
        "rechazados": len(items) - len(aprobados),
        "detalles":   detalles,
    }


def obtener_urls_procesados() -> set[str]:
    urls = set()
    for col in COLECCIONES_URLS:
        for doc in col.find({}, {"url": 1, "_id": 0}):
            if url := doc.get("url"):
                urls.add(url)
    return urls
