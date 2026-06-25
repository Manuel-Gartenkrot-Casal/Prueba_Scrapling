import argparse
import datetime
import sys
import re
from pymongo.errors import OperationFailure
from db import db, crear_indices_texto
from lm_studio import generar_articulo as lm_generar, extraer_temas

FUENTES = {
    "lanacion":    db["autopartes"],
    "aftermarket": db["aftermarket"],
    "ambito":      db["ambito"],
    "cenital":     db["cenital"],
    "perfil":      db["perfil"],
    "custom":      db["custom"],
}

col_articulos = db["articulos_generados"]

TOKENS_POR_CARACTER = 0.28
_OVERHEAD_FIJO = 400
_MARGEN_RESPUESTA = 2048


def _estimar_tokens(texto: str) -> int:
    return max(1, int(len(texto) * TOKENS_POR_CARACTER))


def _formatear_doc(doc: dict, fuente: str, idx: int) -> tuple[str, int]:
    titulo = doc.get("titulo", "(sin título)")
    fecha = doc.get("fecha", "fecha desconocida")
    cuerpo = doc.get("cuerpo", doc.get("bajada", "(sin contenido)"))
    cuerpo = cuerpo[:1500] + "..." if len(cuerpo) > 1500 else cuerpo
    texto = f"[#{idx} - {fuente} - {fecha}] {titulo}\nContenido: {cuerpo}\n"
    return texto, _estimar_tokens(texto)


def _buscar_por_tema(tema: str, limite_por_fuente: int = 20) -> list[tuple[dict, str, float]]:
    resultados = []
    for nombre, coleccion in FUENTES.items():
        try:
            cursor = coleccion.find(
                {"$text": {"$search": tema}},
                {"score": {"$meta": "textScore"}}
            ).sort([("score", {"$meta": "textScore"})]).limit(limite_por_fuente)
            for doc in cursor:
                score = doc.get("score", 0)
                resultados.append((doc, nombre, score))
        except OperationFailure:
            pass
    resultados.sort(key=lambda x: x[2], reverse=True)
    return resultados


def _tema_ya_cubierto(tema: str, umbral: float = 0.1) -> bool:
    try:
        cursor = col_articulos.find(
            {"$text": {"$search": tema}},
            {"score": {"$meta": "textScore"}}
        ).sort([("score", {"$meta": "textScore"})]).limit(1)
        for doc in cursor:
            return doc.get("score", 0) >= umbral
    except OperationFailure:
        pass
    return False


def marcar_usados(coleccion, ids: list) -> None:
    if ids:
        coleccion.update_many(
            {"_id": {"$in": ids}},
            {"$set": {"usado_para_articulo": True}}
        )


def guardar_articulo(contenido: str, ids_usados: list, fuentes: list[str], tema: str) -> None:
    col_articulos.insert_one({
        "contenido":   contenido,
        "fuentes":     fuentes,
        "tema":        tema,
        "docs_usados": [str(i) for i in ids_usados],
        "generado_en": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })


def main():
    parser = argparse.ArgumentParser(description="Generador de artículos con IA + RAG (LM Studio)")
    parser.add_argument(
        "--fuente",
        nargs="+",
        choices=list(FUENTES.keys()),
        default=list(FUENTES.keys()),
        metavar="FUENTE",
        help="Fuentes a usar. Por defecto: todas.",
    )
    parser.add_argument("--max-por-fuente", type=int, default=30)
    parser.add_argument("--budget-contexto", type=int, default=0,
                        help="0 = auto (8192 - márgenes)")
    parser.add_argument("--threshold-dedup", type=float, default=0.1,
                        help="Umbral textScore para considerar tema cubierto (default: 0.1)")
    args = parser.parse_args()

    # ── Asegurar índices de texto ────────────────────────────────────────
    crear_indices_texto()

    # ── Presupuesto ──────────────────────────────────────────────────────
    if args.budget_contexto <= 0:
        args.budget_contexto = 8192 - _MARGEN_RESPUESTA
    budget_docs = args.budget_contexto - _OVERHEAD_FIJO

    # ── 1. Traer recientes para extraer temas ────────────────────────────
    recientes: list[dict] = []
    for nombre in args.fuente:
        docs = list(FUENTES[nombre].find().sort("_id", -1).limit(5))
        print(f"{nombre:<12} {len(docs)} docs recientes")
        recientes.extend(docs)

    if not recientes:
        print("No hay documentos en la base de datos.")
        return

    # ── 2. Extraer temas candidatos ──────────────────────────────────────
    print("\nExtrayendo temas de los artículos recientes...")
    temas = extraer_temas(recientes)
    print(f"Temas candidatos: {', '.join(temas)}")

    # ── 3. Elegir tema no cubierto ───────────────────────────────────────
    tema_elegido = temas[0]
    for t in temas:
        if not _tema_ya_cubierto(t, args.threshold_dedup):
            tema_elegido = t
            break
    print(f"Tema seleccionado: {tema_elegido}")

    # ── 4. $text search en todas las fuentes ─────────────────────────────
    print(f"Buscando documentos relacionados con: {tema_elegido}")
    resultados = _buscar_por_tema(tema_elegido, args.max_por_fuente)

    if not resultados:
        print("Sin resultados de búsqueda, fallback a recencia.")
        todos: list[tuple[dict, str]] = []
        for nombre in args.fuente:
            for d in FUENTES[nombre].find().sort("_id", -1).limit(args.max_por_fuente):
                todos.append((d, nombre))
        todos.sort(key=lambda x: x[0]["_id"], reverse=True)
        rankeados = [(d, f, 0) for d, f in todos]
    else:
        rankeados = resultados

    # ── 5. Llenar budget con los mejores docs ────────────────────────────
    contexto = ""
    seleccionados = []
    tokens_usados = _OVERHEAD_FIJO
    idx = 0

    for doc, fuente, score in rankeados:
        texto_doc, tokens_doc = _formatear_doc(doc, fuente, idx + 1)
        if tokens_usados + tokens_doc > budget_docs:
            continue
        tokens_usados += tokens_doc
        idx += 1
        contexto += f"\n── Fuente: {fuente}{f' (relevancia: {score:.2f})' if score else ''} ──\n" + texto_doc
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
    guardar_articulo(articulo, todos_ids, fuentes_usadas, tema_elegido)

    for nombre in fuentes_usadas:
        ids_fuente = [doc["_id"] for doc, f in seleccionados if f == nombre]
        marcar_usados(FUENTES[nombre], ids_fuente)

    print(f"\nArtículo guardado en la colección 'articulos_generados'.")


if __name__ == "__main__":
    main()
