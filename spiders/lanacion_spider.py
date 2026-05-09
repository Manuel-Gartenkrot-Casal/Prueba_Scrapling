from scrapling.spiders import Spider, Request, Response
from scrapling.fetchers import AsyncDynamicSession

class LanacionSpider(Spider):
    name = "lanacion"
    start_urls = ["https://www.lanacion.com.ar/buscador/?query=autopartes"]
    concurrent_requests = 3

    def configure_sessions(self, manager):
        manager.add(
            "default",
            AsyncDynamicSession(
                headless=True,
                network_idle=True,   # espera a que el JS termine de cargar
                disable_resources=False,
            )
        )

    async def parse(self, response: Response):
        links = response.css('a[onmousedown]::attr(href)').getall()
        print(f"Links encontrados: {len(links)}")  # para verificar

        for link in links:
            url_completa = f"https://www.lanacion.com.ar{link}"
            yield Request(
                url=url_completa,
                callback=self.parse_articulo
            )

    async def parse_articulo(self, response: Response):
        yield {
            "titulo": response.css('h1::text').get(),
            "fecha":  response.css('time::text').get(),
            "cuerpo": " ".join(response.css('p::text').getall()),
            "url":    response.url,
        }