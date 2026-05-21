"""
generar_articulo.py

Lee artículos scrapeados de MongoDB y genera un artículo
periodístico usando la API de NVIDIA. El artículo generado
se guarda en la colección 'articulos_generados'.

Requiere: archivo .env en la raíz con NVIDIA_API_KEY=tu_clave

Uso:
    python generar_articulo.py                     # usa ambas fuentes, 3 docs c/u
    python generar_articulo.py --fuente lanacion   # solo La Nacion
    python generar_articulo.py --fuente aftermarket
    python generar_articulo.py --cantidad 5        # 5 docs por fuente
"""

import argparse
import datetime
import json
import os
import requests
from dotenv import load_dotenv
from db import db

load_dotenv()

# ── Configuración ─────────────────────────────────────────────────────────────

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODELO         = "google/gemma-3n-e4b-it"

col_autopartes  = db["autopartes"]
col_aftermarket = db["aftermarket"]
col_articulos   = db["articulos_generados"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def traer_documentos(coleccion, cantidad: int) -> list[dict]:
    return list(
        coleccion.find({"usado_para_articulo": {"$ne": True}}).limit(cantidad)
    )


def marcar_usados(coleccion, ids: list) -> None:
    if ids:
        coleccion.update_many(
            {"_id": {"$in": ids}},
            {"$set": {"usado_para_articulo": True}}
        )


def formatear_contexto(docs: list[dict], fuente: str) -> str:
    if not docs:
        return ""
    lineas = [f"\n── Fuente: {fuente} ──\n"]
    for doc in docs:
        titulo = doc.get("titulo", "(sin título)")
        cuerpo = doc.get("cuerpo", doc.get("bajada", "(sin contenido)"))
        cuerpo = cuerpo[:1500] + "..." if len(cuerpo) > 1500 else cuerpo
        lineas.append(f"Título: {titulo}\nContenido: {cuerpo}\n")
    return "\n".join(lineas)


def generar_articulo(contexto: str) -> str:
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        raise ValueError("Falta NVIDIA_API_KEY en el archivo .env")

    prompt = f"""Sos un redactor periodístico especializado en la industria automotriz y \
el sector autopartista argentino.

A partir de los siguientes artículos scrapeados de distintos medios, \
escribí UN SOLO artículo de blog original, atractivo y bien estructurado.

Requisitos:
- Título llamativo
- Introducción que enganche al lector
- Desarrollo que integre la información de todas las fuentes
- Cierre con conclusión o perspectiva del sector
- Tono profesional pero accesible
- Extensión: entre 400 y 600 palabras
- En español (Argentina)

Información disponible:
{contexto}"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream",
    }
    payload = {
        "model": MODELO,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024,
        "temperature": 0.70,
        "top_p": 0.70,
        "stream": True,
    }

    response = requests.post(NVIDIA_API_URL, headers=headers, json=payload, stream=True)
    response.raise_for_status()

    articulo = ""
    for line in response.iter_lines():
        if not line:
            continue
        text = line.decode("utf-8")
        if text.startswith("data: "):
            text = text[6:]
        if text == "[DONE]":
            break
        try:
            chunk = json.loads(text)
            delta = chunk["choices"][0]["delta"].get("content", "")
            articulo += delta
            print(delta, end="", flush=True)
        except (json.JSONDecodeError, KeyError):
            continue

    print()  # salto de línea final
    return articulo


def guardar_articulo(contenido: str, ids_usados: list, fuentes: list[str]) -> None:
    col_articulos.insert_one({
        "contenido":   contenido,
        "fuentes":     fuentes,
        "docs_usados": [str(i) for i in ids_usados],
        "generado_en": datetime.datetime.utcnow().isoformat(),
    })

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generador de artículos con IA (NVIDIA)")
    parser.add_argument("--fuente",   choices=["lanacion", "aftermarket", "ambas"], default="ambas")
    parser.add_argument("--cantidad", type=int, default=3)
    args = parser.parse_args()

    docs_lanacion    = []
    docs_aftermarket = []

    if args.fuente in ("lanacion", "ambas"):
        docs_lanacion = traer_documentos(col_autopartes, args.cantidad)
        print(f"La Nacion:    {len(docs_lanacion)} documentos")

    if args.fuente in ("aftermarket", "ambas"):
        docs_aftermarket = traer_documentos(col_aftermarket, args.cantidad)
        print(f"Aftermarket:  {len(docs_aftermarket)} documentos")

    todos = docs_lanacion + docs_aftermarket
    if not todos:
        print("No hay documentos nuevos para procesar. Todos ya fueron usados.")
        return

    contexto = ""
    if docs_lanacion:    contexto += formatear_contexto(docs_lanacion, "La Nacion")
    if docs_aftermarket: contexto += formatear_contexto(docs_aftermarket, "Mundo Aftermarket")

    print("\nGenerando artículo...\n" + "="*60)
    articulo = generar_articulo(contexto)
    print("="*60)

    ids     = [doc["_id"] for doc in todos]
    fuentes = []
    if docs_lanacion:    fuentes.append("lanacion")
    if docs_aftermarket: fuentes.append("aftermarket")

    guardar_articulo(articulo, ids, fuentes)
    marcar_usados(col_autopartes,  [d["_id"] for d in docs_lanacion])
    marcar_usados(col_aftermarket, [d["_id"] for d in docs_aftermarket])

    print(f"\n✅ Artículo guardado en la colección 'articulos_generados'.")


if __name__ == "__main__":
    main()
