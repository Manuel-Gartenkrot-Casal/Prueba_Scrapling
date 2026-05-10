from spiders.aftermarket_spider import AftermarketSpider

result = AftermarketSpider().start()

print(f"Artículos scrapeados: {len(result.items)}")
result.items.to_json("data/aftermarket.json")