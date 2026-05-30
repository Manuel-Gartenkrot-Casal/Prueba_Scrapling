"""
generar_articulo.py

Lee artículos scrapeados de MongoDB y genera un artículo
periodístico usando la API de NVIDIA. El artículo generado
se guarda en la colección 'articulos_generados'.

Requiere: archivo .env en la raíz con NVIDIA_API_KEY=tu_clave

Uso:
    python generar_articulo.py                          # todas las fuentes, 3 docs c/u
    python generar_articulo.py --fuente lanacion        # solo La Nacion
    python generar_articulo.py --fuente aftermarket
    python generar_articulo.py --fuente ambito
    python generar_articulo.py --fuente cenital
    python generar_articulo.py --fuente perfil
    python generar_articulo.py --fuente lanacion ambito # múltiples fuentes
    python generar_articulo.py --cantidad 5             # 5 docs por fuente
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

    print()
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
    parser.add_argument(
        "--fuente",
        nargs="+",
        choices=list(FUENTES.keys()),
        default=list(FUENTES.keys()),
        metavar="FUENTE",
        help=f"Fuentes a usar: {', '.join(FUENTES.keys())}. Por defecto: todas.",
    )
    parser.add_argument("--cantidad", type=int, default=3)
    args = parser.parse_args()

    # Recolectar docs por fuente (guardamos la asociación para marcar usados correctamente)
    docs_por_fuente: dict[str, list[dict]] = {}
    for nombre in args.fuente:
        docs = traer_documentos(FUENTES[nombre], args.cantidad)
        print(f"{nombre:<12} {len(docs)} documentos")
        if docs:
            docs_por_fuente[nombre] = docs

    if not docs_por_fuente:
        print("No hay documentos nuevos para procesar. Todos ya fueron usados.")
        return

    # Armar contexto
    contexto = ""
    for nombre, docs in docs_por_fuente.items():
        contexto += formatear_contexto(docs, nombre)

    total = sum(len(d) for d in docs_por_fuente.values())
    fuentes_usadas = list(docs_por_fuente.keys())
    print(f"\nGenerando artículo con {total} documentos de {len(fuentes_usadas)} fuente/s...\n" + "="*60)

    articulo = generar_articulo(contexto)
    print("="*60)

    # Guardar artículo
    todos_ids = [doc["_id"] for docs in docs_por_fuente.values() for doc in docs]
    guardar_articulo(articulo, todos_ids, fuentes_usadas)

    # Marcar como usados en cada colección correspondiente
    for nombre, docs in docs_por_fuente.items():
        marcar_usados(FUENTES[nombre], [doc["_id"] for doc in docs])

    print(f"\n✅ Artículo guardado en la colección 'articulos_generados'.")


if __name__ == "__main__":
    main()
