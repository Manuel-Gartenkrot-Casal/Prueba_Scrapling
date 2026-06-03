"""
generar_articulo.py

Lee los artículos scrapeados de MongoDB y, POR CADA artículo, genera una
versión nueva reescrita con IA (API de NVIDIA). Es decir: si hay 3 artículos
scrapeados, produce 3 artículos nuevos (uno por cada original), redactados de
otra manera. Cada artículo generado se guarda en la colección
'articulos_generados', referenciando al original del que salió.

Requiere: archivo .env en la raíz con NVIDIA_API_KEY=tu_clave

Uso:
    python generar_articulo.py                          # todas las fuentes, 3 docs c/u
    python generar_articulo.py --fuente lanacion        # solo La Nacion
    python generar_articulo.py --fuente lanacion ambito # múltiples fuentes
    python generar_articulo.py --cantidad 5             # hasta 5 docs por fuente
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

# Recortamos el cuerpo original para no pasarnos de contexto del modelo.
MAX_CHARS_CUERPO = 4000

FUENTES = {
    "lanacion":    db["autopartes"],
    "aftermarket": db["aftermarket"],
    "ambito":      db["ambito"],
    "cenital":     db["cenital"],
    "perfil":      db["perfil"],
}

col_articulos = db["articulos_generados"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def traer_documentos(coleccion, cantidad: int) -> list[dict]:
    return list(
        coleccion.find({"usado_para_articulo": {"$ne": True}}).limit(cantidad)
    )


def marcar_usado(coleccion, _id) -> None:
    coleccion.update_one({"_id": _id}, {"$set": {"usado_para_articulo": True}})


def reescribir(titulo: str, cuerpo: str) -> str:
    """Le pide a la IA una versión nueva y original del artículo recibido."""
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        raise ValueError("Falta NVIDIA_API_KEY en el archivo .env")

    cuerpo = cuerpo[:MAX_CHARS_CUERPO]

    prompt = f"""Sos un redactor periodístico especializado en la industria automotriz y \
el sector autopartista argentino.

Reescribí la siguiente nota como un artículo NUEVO y original, con tus propias palabras.

Requisitos:
- Generá un título nuevo y atractivo, distinto al original.
- Mantené los hechos, datos y la información clave, pero cambiá por completo la \
redacción, el enfoque y la estructura.
- No copies frases textuales de la nota original.
- Tono profesional pero accesible, en español (Argentina).
- Extensión similar a la nota original.
- Devolvé únicamente el artículo (título + cuerpo), sin comentarios ni aclaraciones tuyas.

Nota original:
Título: {titulo}
Contenido: {cuerpo}"""

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

    print()
    return articulo


def guardar_articulo(contenido: str, doc: dict, fuente: str) -> None:
    col_articulos.insert_one({
        "contenido":       contenido,
        "fuente":          fuente,
        "titulo_original": doc.get("titulo", ""),
        "url_original":    doc.get("url", ""),
        "doc_usado":       str(doc["_id"]),
        "generado_en":     datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Reescribe con IA (NVIDIA) cada artículo scrapeado en uno nuevo."
    )
    parser.add_argument(
        "--fuente",
        nargs="+",
        choices=list(FUENTES.keys()),
        default=list(FUENTES.keys()),
        metavar="FUENTE",
        help=f"Fuentes a usar: {', '.join(FUENTES.keys())}. Por defecto: todas.",
    )
    parser.add_argument("--cantidad", type=int, default=3,
                        help="Máximo de artículos a reescribir por fuente (default 3).")
    args = parser.parse_args()

    total_generados = 0

    for nombre in args.fuente:
        coleccion = FUENTES[nombre]
        docs = traer_documentos(coleccion, args.cantidad)
        print(f"{nombre:<12} {len(docs)} artículo(s) para reescribir")

        for doc in docs:
            titulo = doc.get("titulo") or "(sin título)"
            cuerpo = (doc.get("cuerpo") or doc.get("bajada") or "").strip()

            if not cuerpo:
                print(f"  - '{titulo}': sin cuerpo, se omite.")
                continue

            print("\n" + "=" * 60)
            print(f"  NUEVO ARTÍCULO  [{nombre}]  basado en: {titulo}")
            print("=" * 60)

            nuevo = reescribir(titulo, cuerpo)
            guardar_articulo(nuevo, doc, nombre)
            marcar_usado(coleccion, doc["_id"])
            total_generados += 1

    print("\n" + "=" * 60)
    if total_generados == 0:
        print("No hay artículos nuevos para reescribir (todos ya fueron usados).")
    else:
        print(f"✅ {total_generados} artículo(s) nuevo(s) guardado(s) en 'articulos_generados'.")


if __name__ == "__main__":
    main()
