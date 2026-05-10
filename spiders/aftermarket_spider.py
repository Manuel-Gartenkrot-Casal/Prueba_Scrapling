import re
from scrapling.spiders import Spider, Request, Response

BASURA = [
    "Un sitio multimedia integral",
    "corresponsales en Brasil y México",
    "Podes compartir esta nota",
    "activa JavaScript",
    "Nombre *",
    "Correo electrónico *",
]

def limpiar(texto: str) -> str:
    texto = texto.replace("\xa0", " ").strip()
    if any(b in texto for b in BASURA):
        return ""
    return texto

class AftermarketSpider(Spider):
    name = "aftermarket"
    start_urls = ["https://mundoaftermarket.com/mercado/"]
    concurrent_requests = 5

    async def parse(self, response: Response):
        links = response.css('h3 a::attr(href)').getall()

        # Scrapea los artículos de la página actual
        for link in links:
            yield Request(url=link, callback=self.parse_articulo)

        # Si había artículos, va a la siguiente página
        if links:
            match = re.search(r'/page/(\d+)', response.url)
            siguiente = int(match.group(1)) + 1 if match else 2
            yield Request(
                url=f"https://mundoaftermarket.com/mercado/page/{siguiente}/",
                callback=self.parse
            )

    async def parse_articulo(self, response: Response):
        parrafos = [
            limpiar(p) for p in response.css('p::text').getall()
            if len(p.strip()) > 30
        ]
        yield {
            "titulo": response.css('h1::text').get("").strip(),
            "bajada": response.css('h3::text').get("").strip(),
            "cuerpo": " ".join(p for p in parrafos if p),
            "url":    response.url,
        }