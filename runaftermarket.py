from spiders.aftermarket_spider import AftermarketSpider
from db import col_aftermarket, guardar_items

result = AftermarketSpider().start()

items = list(result.items)
print(f"Artículos scrapeados: {len(items)}")

guardados = guardar_items(items, col_aftermarket)
print(f"Guardados/actualizados en MongoDB: {guardados}")
