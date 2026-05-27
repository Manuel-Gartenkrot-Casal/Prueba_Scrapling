from spiders.cenital_spider import CenitalSpider
from db import col_cenital, guardar_items

result = CenitalSpider().start()

items = list(result.items)
print(f"Artículos scrapeados: {len(items)}")
for item in items:
    print(item["titulo"])

guardados = guardar_items(items, col_cenital)
print(f"Guardados/actualizados en MongoDB: {guardados}")
