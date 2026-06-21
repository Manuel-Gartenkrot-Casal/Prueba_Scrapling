import sys
import json
from spiders.scraper_generico import start as scraper_generico
from db import col_custom, clasificar_y_guardar
from lm_studio import clasificar_articulo

data = json.loads(sys.argv[1])
urls = data.get("urls", [])
max_articulos = data.get("max", 5)
modo = data.get("modo", "list")

if not urls:
    print("Error: lista de URLs vacía")
    exit(1)

result = scraper_generico(urls, max_articulos, modo)
items = list(result.items)
print(f"\nArtículos encontrados: {len(items)}")
for item in items:
    print(f"  · {item['titulo']}")

if items:
    print("\n━━━ Evaluando con LM Studio ━━━")
    stats = clasificar_y_guardar(items, col_custom, clasificar_articulo)
    for d in stats["detalles"]:
        icono = "✓" if d["estado"] == "aprobado" else "✗"
        razon = f" → {d['razon']}" if "razon" in d else ""
        print(f"  {icono} \"{d['titulo']}\"{razon}")
    print(f"\n━━━ Resultado ━━━")
    print(f"  Aprobados:  {stats['aprobados']}")
    print(f"  Rechazados: {stats['rechazados']}")
else:
    print("\nNo hay artículos para clasificar.")
