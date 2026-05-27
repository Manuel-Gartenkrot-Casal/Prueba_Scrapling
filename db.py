from pymongo import MongoClient

MONGO_URI = "mongodb+srv://48792944_db_user:3J7mqbFWfQ9EmdCh@pruebascrapling.uo6x74d.mongodb.net/?appName=PruebaScrapling"

client = MongoClient(MONGO_URI)
db = client["PruebaScrapling"]

col_lanacion    = db["autopartes"]    # artículos de La Nacion
col_aftermarket = db["aftermarket"]   # artículos de Mundo Aftermarket
col_ambito      = db["ambito"]        # artículos de Ambito Financiero
col_cenital     = db["cenital"]       # artículos de Cenital
col_perfil      = db["perfil"]        # artículos de Perfil


def guardar_items(items, coleccion):
    """
    Inserta una lista de dicts en la colección indicada.
    Usa update_replace con upsert=True sobre 'url' para evitar duplicados.
    """
    if not items:
        return 0

    from pymongo import ReplaceOne
    operaciones = [
        ReplaceOne({"url": item["url"]}, item, upsert=True)
        for item in items
    ]
    resultado = coleccion.bulk_write(operaciones)
    return resultado.upserted_count + resultado.modified_count
