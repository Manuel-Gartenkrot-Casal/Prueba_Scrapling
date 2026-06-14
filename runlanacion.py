from spiders.lanacion_spider import LanacionSpider
from db import col_lanacion, clasificar_y_guardar
from lm_studio import clasificar_articulo

try:
    result = LanacionSpider().start()
except Exception as e:
    print(f"Error al ejecutar spider: {e}")
    exit(1)

items = list(result.items)
print(f"Artículos encontrados: {len(items)}")
for item in items:
    print(f"  · {item['titulo']}")

print("\n━━━ Evaluando con LM Studio ━━━")
stats = clasificar_y_guardar(items, col_lanacion, clasificar_articulo)

for d in stats["detalles"]:
    icono = "✓" if d["estado"] == "aprobado" else "✗"
    razon = f" → {d['razon']}" if "razon" in d else ""
    print(f"  {icono} \"{d['titulo']}\"{razon}")

print(f"\n━━━ Resultado ━━━")
print(f"  Aprobados:  {stats['aprobados']}")
print(f"  Rechazados: {stats['rechazados']}")
print(f"  (Descartados guardados en colección 'articulos_descartados')")
