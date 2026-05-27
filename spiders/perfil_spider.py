from scrapling.spiders import Spider, Request, Response
from scrapling.fetchers import AsyncDynamicSession


class PerfilSpider(Spider):
    """
    Scrapea artículos sobre autopartes de Perfil.com.
    El buscador usa Google Custom Search (carga con JS), por eso necesita
    AsyncDynamicSession con network_idle=True.
    """
    name = "perfil"
    start_urls = [
        "https://www.perfil.com/buscador?q=autopartes#gsc.tab=0&gsc.q=autopartes&gsc.page=1"
    ]
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
        """
        Google Custom Search embebido: los resultados están en .gsc-result .gs-title a.
        También intentamos selectores nativos de Perfil por si cambian la implementación.
        """
        # Selectores Google CSE (carga dinámica)
        gsc_links = response.css(
            ".gsc-result .gs-title a::attr(href), "
            ".gsc-results .gsc-result a.gs-title::attr(href)"
        ).getall()

        # Selectores nativos de Perfil como fallback
        perfil_links = response.css(
            "a[href*='perfil.com/noticias']::attr(href), "
            "a[href*='/noticias/']::attr(href), "
            "h2 a::attr(href), h3 a::attr(href)"
        ).getall()

        links = gsc_links if gsc_links else perfil_links

        # Filtrar solo URLs de Perfil y normalizar
        seen = set()
        for link in links:
            # Google CSE a veces devuelve URLs con prefijo de redirección
            if "perfil.com" not in link:
                continue
            # Limpiar parámetros de rastreo de Google
            link = link.split("&")[0] if "?sa=" in link else link
            if link not in seen:
                seen.add(link)
                yield Request(url=link, callback=self.parse_articulo)

        # Paginación Google CSE: página siguiente en `.gsc-cursor-page`
        import re

        current_page_match = re.search(r"gsc\.page=(\d+)", response.url)
        current_page = int(current_page_match.group(1)) if current_page_match else 1

        # Botón de siguiente página en Google CSE
        next_btn = response.css(".gsc-cursor-next-page::attr(style)").get()
        has_next = next_btn is None or "display:none" not in next_btn

        if links and has_next and current_page <= 5:
            next_page = current_page + 1
            yield Request(
                url=f"https://www.perfil.com/buscador?q=autopartes#gsc.tab=0&gsc.q=autopartes&gsc.page={next_page}",
                callback=self.parse,
            )

    async def parse_articulo(self, response: Response):
        title = (
            response.css("h1.title-nota::text").get()
            or response.css("h1[class*='title']::text").get()
            or response.css("h1[class*='nota']::text").get()
            or response.css("h1::text").get()
            or ""
        ).strip()

        date = (
            response.css("time::attr(datetime)").get()
            or response.css("time::text").get()
            or response.css("[class*='fecha']::text").get()
            or response.css("[class*='date']::text").get()
            or ""
        ).strip()

        author = (
            response.css("[class*='author'] a::text").get()
            or response.css("[class*='firma']::text").get()
            or response.css(".byline::text").get()
            or ""
        ).strip()

        parrafos = [
            p.strip()
            for p in response.css(
                ".article-body p::text, "
                ".nota-content p::text, "
                "[class*='article-content'] p::text, "
                "[class*='body-nota'] p::text, "
                "article p::text"
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
