from spiders.ambito_spider import AmbitoSpider
from db import col_ambito, guardar_items

result = AmbitoSpider().start()

items = list(result.items)
print(f"Artículos scrapeados: {len(items)}")
for item in items:
    print(item["titulo"])

guardados = guardar_items(items, col_ambito)
print(f"Guardados/actualizados en MongoDB: {guardados}")
