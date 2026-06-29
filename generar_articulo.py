"""
generar_articulo.py — Genera un artículo original a partir de los scrapeados, usando
embeddings para elegir un tópico coherente y fresco (no repetido).

Flujo (ver charla de diseño):
  1. Cargar todos los artículos que tienen embedding.
  2. Cargar los artículos ya generados (con su embedding) → memoria de lo escrito.
  3. Elegir SEMILLA por frescura: el artículo que MENOS se parece a lo ya generado
     (y entre iguales, el más reciente). Así evita arrancar de un tópico ya cubierto.
  4. Armar el tópico: semilla + sus K vecinos más cercanos (k-NN) por encima de un
     umbral de similitud → paquete temático coherente.
  5. Redactar con LM Studio usando solo ese paquete (contexto denso y enfocado).
  6. Dedup de salida: vectorizar el artículo generado; si se parece demasiado a uno
     previo, descartarlo y probar con la siguiente semilla.
  7. Guardar el artículo CON su embedding (para el dedup futuro) y marcar usados.
"""

import argparse
import datetime
import sys

from db import db
from lm_studio import generar_articulo as lm_generar, calcular_embedding
from embeddings import coseno, texto_para_embedding

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

# Parámetros de selección por embeddings (calibrados con la data real).
UMBRAL_TOPICO = 0.70   # similitud mínima para considerar a un doc "vecino" de la semilla
MIN_VECINOS   = 2      # una semilla necesita al menos esta cantidad de vecinos
K_VECINOS     = 8      # cuántos vecinos como máximo entran al tópico
UMBRAL_DEDUP  = 0.85   # si el artículo generado supera esto vs uno previo, se descarta
MAX_INTENTOS  = 4      # cuántas semillas probar antes de rendirse


def _estimar_tokens(texto: str) -> int:
    return max(1, int(len(texto) * TOKENS_POR_CARACTER))


def _formatear_doc(doc: dict, fuente: str, idx: int) -> tuple[str, int]:
    titulo = doc.get("titulo", "(sin título)")
    fecha = doc.get("fecha", "fecha desconocida")
    cuerpo = doc.get("cuerpo", doc.get("bajada", "(sin contenido)"))
    cuerpo = cuerpo[:1500] + "..." if len(cuerpo) > 1500 else cuerpo
    texto = f"[#{idx} - {fuente} - {fecha}] {titulo}\nContenido: {cuerpo}\n"
    return texto, _estimar_tokens(texto)


def _cargar_candidatos(fuentes: list[str]) -> list[dict]:
    """Todos los artículos con embedding de las fuentes elegidas."""
    candidatos = []
    for nombre in fuentes:
        for d in FUENTES[nombre].find({"embedding": {"$exists": True}}):
            d["_fuente"] = nombre
            candidatos.append(d)
    return candidatos


def _cargar_generados_emb() -> list[list[float]]:
    """
    Embeddings de los artículos ya generados (memoria de lo escrito).
    Calcula y persiste el embedding de los que aún no lo tengan.
    """
    vecs = []
    for g in col_articulos.find():
        vec = g.get("embedding")
        if not vec:
            vec = calcular_embedding(g.get("contenido", ""))
            if vec:
                col_articulos.update_one({"_id": g["_id"]}, {"$set": {"embedding": vec}})
        if vec:
            vecs.append(vec)
    return vecs


def _novedad(vec: list[float], generados: list[list[float]]) -> float:
    """1 - (máxima similitud con lo ya generado). 1.0 = tema totalmente nuevo."""
    if not generados:
        return 1.0
    return 1.0 - max(coseno(vec, g) for g in generados)


def _vecinos(semilla: dict, candidatos: list[dict]) -> list[tuple[dict, float]]:
    """Vecinos de la semilla por encima del umbral, ordenados por similitud desc."""
    sem_vec = semilla["embedding"]
    cercanos = []
    for d in candidatos:
        if d["_id"] == semilla["_id"]:
            continue
        s = coseno(sem_vec, d["embedding"])
        if s >= UMBRAL_TOPICO:
            cercanos.append((d, s))
    cercanos.sort(key=lambda x: x[1], reverse=True)
    return cercanos[:K_VECINOS]


def guardar_articulo(contenido, ids_usados, fuentes, tema, embedding) -> None:
    col_articulos.insert_one({
        "contenido":   contenido,
        "fuentes":     fuentes,
        "tema":        tema,
        "docs_usados": [str(i) for i in ids_usados],
        "embedding":   embedding,
        "generado_en": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })


def marcar_usados(coleccion, ids: list) -> None:
    if ids:
        coleccion.update_many({"_id": {"$in": ids}}, {"$set": {"usado_para_articulo": True}})


def main():
    parser = argparse.ArgumentParser(description="Generador de artículos con IA + embeddings (LM Studio)")
    parser.add_argument("--fuente", nargs="+", choices=list(FUENTES.keys()),
                        default=list(FUENTES.keys()), metavar="FUENTE",
                        help="Fuentes a usar. Por defecto: todas.")
    parser.add_argument("--budget-contexto", type=int, default=0, help="0 = auto (8192 - márgenes)")
    args = parser.parse_args()

    budget = (args.budget_contexto if args.budget_contexto > 0 else 8192 - _MARGEN_RESPUESTA) - _OVERHEAD_FIJO

    # ── 1-2. Cargar candidatos y memoria de lo ya generado ───────────────
    candidatos = _cargar_candidatos(args.fuente)
    print(f"Artículos con embedding disponibles: {len(candidatos)}")
    if not candidatos:
        print("No hay artículos vectorizados. Corré primero el backfill (embeddings.py).")
        return

    generados = _cargar_generados_emb()
    print(f"Artículos ya generados (memoria anti-repetición): {len(generados)}")

    # ── 3. Ordenar semillas por frescura (y recencia como desempate) ─────
    candidatos.sort(
        key=lambda d: (_novedad(d["embedding"], generados), d["_id"].generation_time.timestamp()),
        reverse=True,
    )

    # ── 4-7. Probar semillas hasta lograr un artículo no repetido ────────
    for intento, semilla in enumerate(candidatos[:MAX_INTENTOS], 1):
        tema = semilla.get("titulo", "(sin título)")
        print(f"\n── Intento {intento}: semilla → {tema[:70]}")

        vecinos = _vecinos(semilla, candidatos)
        if len(vecinos) < MIN_VECINOS:
            print(f"   semilla con pocos vecinos ({len(vecinos)}), probando otra...")
            continue

        # Armar el paquete temático: semilla + vecinos, hasta llenar el budget.
        paquete = [(semilla, semilla["_fuente"], 1.0)] + [(d, d["_fuente"], s) for d, s in vecinos]
        contexto = ""
        seleccionados = []
        tokens = _OVERHEAD_FIJO
        for idx, (doc, fuente, sim) in enumerate(paquete, 1):
            texto_doc, t = _formatear_doc(doc, fuente, idx)
            if tokens + t > budget:
                continue
            tokens += t
            contexto += f"\n── Fuente: {fuente} (afinidad: {sim:.2f}) ──\n" + texto_doc
            seleccionados.append((doc, fuente))

        print(f"   tópico armado: {len(seleccionados)} artículos (~{tokens} tokens)")
        print("=" * 60)
        try:
            articulo = lm_generar(contexto)
        except Exception as e:
            print(f"\nError al generar: {e}")
            sys.exit(1)
        print("=" * 60)

        if not articulo:
            print("   artículo vacío, probando otra semilla...")
            continue

        # ── 6. Dedup de salida ───────────────────────────────────────────
        emb_art = calcular_embedding(articulo)
        if emb_art and generados:
            parecido = max(coseno(emb_art, g) for g in generados)
            if parecido >= UMBRAL_DEDUP:
                print(f"   ✗ demasiado parecido a uno previo (sim {parecido:.2f}), descartado. Otra semilla...")
                continue

        # ── 7. Guardar ───────────────────────────────────────────────────
        ids = [d["_id"] for d, _ in seleccionados]
        fuentes_usadas = list({f for _, f in seleccionados})
        guardar_articulo(articulo, ids, fuentes_usadas, tema, emb_art)
        for nombre in fuentes_usadas:
            marcar_usados(FUENTES[nombre], [d["_id"] for d, f in seleccionados if f == nombre])

        print(f"\n✓ Artículo guardado (tema: {tema[:50]}) usando {len(seleccionados)} fuentes.")
        return

    print(f"\nNo se logró un artículo nuevo tras {MAX_INTENTOS} intentos (todo muy parecido a lo ya escrito).")


if __name__ == "__main__":
    main()
