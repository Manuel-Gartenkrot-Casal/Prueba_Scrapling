from scrapling.spiders import Spider, Request, Response
from scrapling.fetchers import AsyncDynamicSession


class CenitalSpider(Spider):
    """
    Scrapea artículos sobre autopartes de Cenital.com.
    WordPress con búsqueda estándar + paginación tipo /page/N/.
    Usa AsyncDynamicSession para esquivar bloqueos.
    """
    name = "cenital"
    start_urls = ["https://cenital.com/?s=autopartes"]
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
        # WordPress: artículos en <article> con links en h2/h3
        link_selectors = [
            "article h2 a::attr(href)",
            "article h3 a::attr(href)",
            ".entry-title a::attr(href)",
            ".post-title a::attr(href)",
            "h2.search-entry-title a::attr(href)",
            ".search-results article a[rel='bookmark']::attr(href)",
        ]

        links = []
        for sel in link_selectors:
            links = response.css(sel).getall()
            if links:
                break

        seen = set()
        for link in links:
            if link and link not in seen:
                seen.add(link)
                yield Request(url=link, callback=self.parse_articulo)

        # Paginación WP: /?s=autopartes&paged=2 o /page/2/?s=autopartes
        import re
        match = re.search(r"[?&]paged=(\d+)", response.url)
        current = int(match.group(1)) if match else 1

        # Link explícito de "siguiente"
        next_url = (
            response.css("a.next-page-link::attr(href)").get()
            or response.css("a.next::attr(href)").get()
            or response.css("a[class*='next']::attr(href)").get()
            or response.css(".nav-links a[class*='next']::attr(href)").get()
        )

        if next_url and links and current <= 10:
            yield Request(url=next_url, callback=self.parse)
        elif links and current <= 10:
            next_page = current + 1
            yield Request(
                url=f"https://cenital.com/page/{next_page}/?s=autopartes",
                callback=self.parse,
            )

    async def parse_articulo(self, response: Response):
        title = (
            response.css("h1.entry-title::text").get()
            or response.css("h1.post-title::text").get()
            or response.css("h1::text").get()
            or ""
        ).strip()

        date = (
            response.css("time::attr(datetime)").get()
            or response.css("time::text").get()
            or response.css(".entry-date::text").get()
            or response.css(".posted-on::text").get()
            or ""
        ).strip()

        author = (
            response.css(".author a::text").get()
            or response.css(".byline a::text").get()
            or response.css("[class*='author']::text").get()
            or ""
        ).strip()

        parrafos = [
            p.strip()
            for p in response.css(
                ".entry-content p::text, "
                ".post-content p::text, "
                ".article-content p::text, "
                "article .content p::text"
            ).getall()
            if len(p.strip()) > 30
        ]

        if not title:
            return

        yield {
            "titulo": title,
            "fecha": date,
            "autor": author,
            "cuerpo": " ".join(parrafos),
            "url": response.url,
        }
