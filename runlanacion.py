from spiders.lanacion_spider import LanacionSpider
from db import col_lanacion, guardar_items

result = LanacionSpider().start()

items = list(result.items)
print(f"Artículos scrapeados: {len(items)}")
for item in items:
    print(item["titulo"])

guardados = guardar_items(items, col_lanacion)
print(f"Guardados/actualizados en MongoDB: {guardados}")
