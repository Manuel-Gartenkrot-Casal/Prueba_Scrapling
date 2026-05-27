from scrapling.spiders import Spider, Request, Response
from scrapling.fetchers import AsyncDynamicSession


class AmbitoSpider(Spider):
    """
    Scrapea artículos de la sección Industria Automotriz de Ambito Financiero.
    Usa AsyncDynamicSession (Playwright) porque el sitio requiere JS.
    """
    name = "ambito"
    start_urls = ["https://www.ambito.com/industria-automotriz-a5127281"]
    concurrent_requests = 3

    def configure_sessions(self, manager):
        manager.add(
            "default",
            AsyncDynamicSession(
                headless=True,
                network_idle=True,
                disable_resources=False,
            ),
        )

    async def parse(self, response: Response):
        # Ambito lista artículos con <article> o con links con /nota/ en el href
        selectors = [
            "article a[href*='/nota/']::attr(href)",
            "a[href*='/nota/']::attr(href)",
            ".article-list a::attr(href)",
            ".listing a[href*='/nota']::attr(href)",
            "h2 a[href*='/nota']::attr(href)",
            "h3 a[href*='/nota']::attr(href)",
        ]

        links = []
        for sel in selectors:
            links = [l for l in response.css(sel).getall() if l]
            if links:
                break

        # Normalizar URLs relativas
        seen = set()
        for link in links:
            if not link.startswith("http"):
                link = "https://www.ambito.com" + link
            if link not in seen:
                seen.add(link)
                yield Request(url=link, callback=self.parse_articulo)

        # Paginación: Ambito usa ?page=N o /page/N
        import re
        match = re.search(r"[?&]page=(\d+)", response.url)
        if match:
            next_page = int(match.group(1)) + 1
        else:
            next_page = 2

        # Solo paginar si encontramos artículos en esta página
        if links and next_page <= 5:
            base = self.start_urls[0].split("?")[0]
            yield Request(
                url=f"{base}?page={next_page}",
                callback=self.parse,
            )

    async def parse_articulo(self, response: Response):
        title = (
            response.css("h1.article-title::text").get()
            or response.css("h1[class*='title']::text").get()
            or response.css("h1::text").get()
            or ""
        ).strip()

        date = (
            response.css("time::attr(datetime)").get()
            or response.css("time::text").get()
            or response.css("[class*='date']::text").get()
            or ""
        ).strip()

        parrafos = [
            p.strip()
            for p in response.css(
                ".article-body p::text, "
                "[class*='article-content'] p::text, "
                "[class*='body'] p::text, "
                "article p::text"
            ).getall()
            if len(p.strip()) > 30
        ]

        if not title:
            return

        yield {
            "titulo": title,
            "fecha": date,
            "cuerpo": " ".join(parrafos),
            "url": response.url,
        }
