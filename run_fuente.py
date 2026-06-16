"""
run_fuente.py

Runner único para cualquier fuente. Reemplaza a los runlanacion.py,
runaftermarket.py, etc. — en lugar de un script por sitio, recibe el nombre de
la fuente, busca su configuración en fuentes.json, la scrapea con el spider
genérico, clasifica los resultados con LM Studio y guarda los aprobados.

Uso:
    python run_fuente.py lanacion
    python run_fuente.py ambito
"""

import sys

from fuentes import get_fuente
from spiders.generic_spider import GenericSpider
from db import get_coleccion, clasificar_y_guardar
from lm_studio import clasificar_articulo


def main():
    if len(sys.argv) < 2:
        print("Uso: python run_fuente.py <nombre_de_fuente>")
        sys.exit(1)

    nombre = sys.argv[1]
    cfg = get_fuente(nombre)
    if not cfg:
        print(f"La fuente '{nombre}' no existe en fuentes.json")
        sys.exit(1)

    try:
        result = GenericSpider(cfg).start()
    except Exception as e:
        print(f"Error al ejecutar spider: {e}")
        sys.exit(1)

    items = list(result.items)
    print(f"Artículos encontrados: {len(items)}")
    for item in items:
        print(f"  · {item['titulo']}")

    print("\n━━━ Evaluando con LM Studio ━━━")
    coleccion = get_coleccion(cfg["coleccion"])
    stats = clasificar_y_guardar(items, coleccion, clasificar_articulo)

    for d in stats["detalles"]:
        icono = "✓" if d["estado"] == "aprobado" else "✗"
        razon = f" → {d['razon']}" if "razon" in d else ""
        print(f"  {icono} \"{d['titulo']}\"{razon}")

    print(f"\n━━━ Resultado ━━━")
    print(f"  Aprobados:  {stats['aprobados']}")
    print(f"  Rechazados: {stats['rechazados']}")
    print(f"  (Descartados guardados en colección 'articulos_descartados')")


if __name__ == "__main__":
    main()
