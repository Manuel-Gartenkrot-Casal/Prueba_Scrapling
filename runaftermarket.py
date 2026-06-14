from spiders.aftermarket_spider import AftermarketSpider
from db import col_aftermarket, clasificar_y_guardar
from lm_studio import clasificar_articulo

result = AftermarketSpider().start()

items = list(result.items)
print(f"Artículos encontrados: {len(items)}")
for item in items:
    print(f"  · {item['titulo']}")

print("\n━━━ Evaluando con LM Studio ━━━")
stats = clasificar_y_guardar(items, col_aftermarket, clasificar_articulo)

for d in stats["detalles"]:
    icono = "✓" if d["estado"] == "aprobado" else "✗"
    razon = f" → {d['razon']}" if "razon" in d else ""
    print(f"  {icono} \"{d['titulo']}\"{razon}")

print(f"\n━━━ Resultado ━━━")
print(f"  Aprobados:  {stats['aprobados']}")
print(f"  Rechazados: {stats['rechazados']}")
print(f"  (Descartados guardados en colección 'articulos_descartados')")
