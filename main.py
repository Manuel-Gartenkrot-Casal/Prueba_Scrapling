from spiders.lanacion_spider import LanacionSpider

result = LanacionSpider().start()

print(f"Artículos scrapeados: {len(result.items)}")
for item in result.items:
    print(item["titulo"])

result.items.to_json("data/autopartes.json")