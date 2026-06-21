import argparse
import datetime
import sys
from db import db
from lm_studio import generar_articulo as lm_generar

FUENTES = {
    "lanacion":    db["autopartes"],
    "aftermarket": db["aftermarket"],
    "ambito":      db["ambito"],
    "cenital":     db["cenital"],
    "perfil":      db["perfil"],
    "custom":      db["custom"],
}

col_articulos = db["articulos_generados"]

TOKENS_POR_CARACTER = 0.28  # ~1 token cada 3.5 caracteres (~4 en español)
_OVERHEAD_FIJO = 400        # system prompt + instrucciones
_MARGEN_RESPUESTA = 2048    # tokens reservados para la respuesta del modelo


def _estimar_tokens(texto: str) -> int:
    return max(1, int(len(texto) * TOKENS_POR_CARACTER))


def traer_documentos(coleccion, cantidad: int) -> list[dict]:
    return list(coleccion.find().sort("_id", -1).limit(cantidad))


def marcar_usados(coleccion, ids: list) -> None:
    if ids:
        coleccion.update_many(
            {"_id": {"$in": ids}},
            {"$set": {"usado_para_articulo": True}}
        )


def guardar_articulo(contenido: str, ids_usados: list, fuentes: list[str]) -> None:
    col_articulos.insert_one({
        "contenido":   contenido,
        "fuentes":     fuentes,
        "docs_usados": [str(i) for i in ids_usados],
        "generado_en": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })


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
    parser.add_argument("--max-por-fuente", type=int, default=30,
                        help="Máximo de documentos a obtener por fuente (default: 30)")
    parser.add_argument("--budget-contexto", type=int, default=0,
                        help="Presupuesto de tokens para el contexto completo. 0 = auto (8192 - márgenes)")
    args = parser.parse_args()

    # ── Calcular presupuesto ──────────────────────────────────────────────
    if args.budget_contexto <= 0:
        args.budget_contexto = 8192 - _MARGEN_RESPUESTA
    budget_docs = args.budget_contexto - _OVERHEAD_FIJO

    # ── Recolectar documentos de todas las fuentes ────────────────────────
    todos: list[tuple[dict, str]] = []  # (doc, nombre_fuente)
    for nombre in args.fuente:
        docs = traer_documentos(FUENTES[nombre], args.max_por_fuente)
        print(f"{nombre:<12} {len(docs)} documentos disponibles")
        for d in docs:
            todos.append((d, nombre))

    if not todos:
        print("No hay documentos en la base de datos.")
        return

    # ── Ordenar por recencia (más reciente primero) y llenar presupuesto ──
    todos.sort(key=lambda x: x[0]["_id"], reverse=True)

    contexto = ""
    seleccionados = []
    tokens_usados = _OVERHEAD_FIJO
    idx = 0

    for doc, fuente in todos:
        titulo = doc.get("titulo", "(sin título)")
        fecha = doc.get("fecha", "fecha desconocida")
        cuerpo = doc.get("cuerpo", doc.get("bajada", "(sin contenido)"))
        cuerpo = cuerpo[:1500] + "..." if len(cuerpo) > 1500 else cuerpo
        texto_doc = f"[#{idx + 1} - {fuente} - {fecha}] {titulo}\nContenido: {cuerpo}\n"

        tokens_doc = _estimar_tokens(texto_doc)
        if tokens_usados + tokens_doc > budget_docs:
            continue
        tokens_usados += tokens_doc
        idx += 1
        contexto += f"\n── Fuente: {fuente} ──\n" + texto_doc
        seleccionados.append((doc, fuente))

    total_seleccion = len(seleccionados)
    print(f"\nUsando {total_seleccion} documentos (~{tokens_usados} tokens de ~{budget_docs} disponibles)")
    print(f"\nGenerando artículo con {total_seleccion} documentos de {len(set(f for _, f in seleccionados))} fuente/s...\n" + "="*60)

    try:
        articulo = lm_generar(contexto)
    except Exception as e:
        print(f"\nError al generar artículo: {e}")
        sys.exit(1)

    print("="*60)

    if not articulo:
        print("El artículo generado está vacío. No se guarda nada.")
        return

    todos_ids = [doc["_id"] for doc, _ in seleccionados]
    fuentes_usadas = list({f for _, f in seleccionados})
    guardar_articulo(articulo, todos_ids, fuentes_usadas)

    for nombre in fuentes_usadas:
        ids_fuente = [doc["_id"] for doc, f in seleccionados if f == nombre]
        marcar_usados(FUENTES[nombre], ids_fuente)

    print(f"\nArtículo guardado en la colección 'articulos_generados'.")


if __name__ == "__main__":
    main()
