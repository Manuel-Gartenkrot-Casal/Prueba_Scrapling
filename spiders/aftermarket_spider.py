from scrapling.spiders import Spider, Request, Response

class AftermarketSpider(Spider):
    name = "aftermarket"
    start_urls = ["https://mundoaftermarket.com/mercado/"]
    concurrent_requests = 5

    async def parse(self, response: Response):
        # Links de artículos
        for link in response.css('h3 a::attr(href)').getall():
            yield Request(url=link, callback=self.parse_articulo)

        # Paginación — WordPress usa esta clase
        next_page = response.css('a.next.page-numbers::attr(href)').get()
        if next_page:
            yield Request(url=next_page, callback=self.parse)

    async def parse_articulo(self, response: Response):
        yield {
            # El sitio usa Elementor, sin clases estándar de WP
            "titulo": response.css('h1::text').get(),
            "bajada": response.css('h3::text').get(),
            "cuerpo": " ".join(
                p for p in response.css('p::text').getall()
                if len(p.strip()) > 30  # filtra basura corta
            ),
            "url": response.url,
        }