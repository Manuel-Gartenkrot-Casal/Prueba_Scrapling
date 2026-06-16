"""
generar_articulo.py

Lee artículos scrapeados de MongoDB y genera un artículo
periodístico usando LM Studio (modelo local). El artículo
generado se guarda en la colección 'articulos_generados'.

Requerimientos: LM Studio corriendo con el modelo configurado en .env

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
import sys
from db import db
from fuentes import cargar_fuentes
from lm_studio import generar_articulo as lm_generar

# ── Configuración ──────────────────────────────────────────────────────────────

# Las fuentes salen de fuentes.json: {nombre: colección} según cada entrada.
FUENTES = {f["nombre"]: db[f["coleccion"]] for f in cargar_fuentes()}

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


def guardar_articulo(contenido: str, ids_usados: list, fuentes: list[str]) -> None:
    col_articulos.insert_one({
        "contenido":   contenido,
        "fuentes":     fuentes,
        "docs_usados": [str(i) for i in ids_usados],
        "generado_en": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generador de artículos con IA (LM Studio)")
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

    try:
        articulo = lm_generar(contexto)
    except Exception as e:
        print(f"\n❌ Error al generar artículo: {e}")
        sys.exit(1)

    print("="*60)

    if not articulo:
        print("El artículo generado está vacío. No se guarda nada.")
        return

    # Guardar artículo
    todos_ids = [doc["_id"] for docs in docs_por_fuente.values() for doc in docs]
    guardar_articulo(articulo, todos_ids, fuentes_usadas)

    # Marcar como usados en cada colección correspondiente
    for nombre, docs in docs_por_fuente.items():
        marcar_usados(FUENTES[nombre], [doc["_id"] for doc in docs])

    print(f"\n✅ Artículo guardado en la colección 'articulos_generados'.")


if __name__ == "__main__":
    main()
