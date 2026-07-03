from spiders.afterdrive_spider import AfterdriveSpider
from db import col_afterdrive, guardar_items
from embeddings import texto_para_embedding
from lm_studio import calcular_embedding

skip_urls = set(d["url"] for d in col_afterdrive.find({}, {"url": 1}))
try:
    result = AfterdriveSpider().start(skip_urls=skip_urls)
except Exception as e:
    print(f"Error al ejecutar spider: {e}")
    exit(1)

items = list(result.items)
print(f"Artículos encontrados: {len(items)}")
for item in items:
    print(f"  · {item['titulo'][:80]}")

vectorizados = 0
for item in items:
    vec = calcular_embedding(texto_para_embedding(item))
    if vec:
        item["embedding"] = vec
        vectorizados += 1

stats = guardar_items(items, col_afterdrive)
print(f"\nGuardados: {stats} (nuevos + modificados)")
print(f"Vectorizados: {vectorizados}/{len(items)}")
