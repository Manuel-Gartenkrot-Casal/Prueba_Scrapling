from spiders.perfil_spider import PerfilSpider
from db import col_perfil, guardar_items

result = PerfilSpider().start()

items = list(result.items)
print(f"Artículos scrapeados: {len(items)}")
for item in items:
    print(item["titulo"])

guardados = guardar_items(items, col_perfil)
print(f"Guardados/actualizados en MongoDB: {guardados}")
