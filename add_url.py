import datetime
import sys

from db import clasificar_y_guardar, col_articulos, col_trusted_urls
from lm_studio import clasificar_articulo
from scheduler import get_max_articulos
from scraper import start


def add_custom_url(url: str):
    print(f"Procesando URL: {url}")

    # 1. Scraping en modo listado: buscar articulos dentro de la pagina
    max_art = get_max_articulos()
    result = start([url], modo="list", max_articulos=max_art)
    items = result.items

    if not items:
        print("[FAIL] No se encontraron articulos en la URL. No se agregara a URLs Confiables.")
        return

    # 2. Clasificar y guardar articulos en la coleccion general
    res = clasificar_y_guardar(items, col_articulos, clasificar_articulo)

    print(f"\nResultado: {res['aprobados']} aprobados, {res['rechazados']} rechazados.")

    if res["aprobados"] > 0:
        # 3. Agregar a URLs Confiables si al menos un articulo fue aprobado
        col_trusted_urls.update_one(
            {"url": url},
            {
                "$set": {
                    "nombre_fuente": items[0].get("fuente", "Custom Source"),
                    "fecha_agregado": datetime.datetime.now(datetime.UTC).isoformat(),
                    "ultima_ejecucion": datetime.datetime.now(datetime.UTC).isoformat(),
                    "estado": "activo",
                }
            },
            upsert=True,
        )
        print("[OK] URL agregada exitosamente a la lista de URLs Confiables.")
    else:
        print("[WARN] Ningun articulo fue aprobado por el clasificador. La URL no se agrego a Confiables.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python add_url.py <URL>")
        sys.exit(1)

    target_url = sys.argv[1]
    add_custom_url(target_url)
