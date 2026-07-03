from scrapling.fetchers import StealthyFetcher

MAX_ARTICULOS = 25

FETCH_OPTS = {"headless": True, "disable_resources": True, "timeout": 25000}

PAGINAS = [
    "https://afterdrive.alephee.com/en/blog/tag/success-stories",
    "https://afterdrive.alephee.com/en/blog/tag/success-stories/page/2",
    "https://afterdrive.alephee.com/en/blog/tag/success-stories/page/3",
]

BASURA = [
    "Conforme a los criterios de",
    "Suscribite",
    "Newsletter",
    "Registrate",
    "Sobre Alephee",
    "Suscripción al",
    "Follow us",
    "After Drive",
    "by Alephee",
    "Related news",
    "Novedades",
    "Previous article",
    "Next article",
    "Ready to start",
    "Schedule a meeting",
]


class _Result:
    def __init__(self, items):
        self.items = items


def _texto(elemento):
    if elemento is None:
        return ""
    return (elemento.get_all_text(strip=True) or "").strip()


def _es_basura(texto: str) -> bool:
    return any(b in texto for b in BASURA)


class AfterdriveSpider:
    name = "afterdrive"
    base = "https://afterdrive.alephee.com"

    def _links(self, url: str) -> list[str]:
        try:
            pag = StealthyFetcher.fetch(url, **FETCH_OPTS)
        except Exception:
            return []
        hrefs = pag.css("h3 a::attr(href)").getall()
        vistos = set()
        links = []
        for href in hrefs:
            if not href:
                continue
            if href.startswith("/"):
                href = self.base + href
            if not href.startswith(self.base) or "/en/blog/" not in href:
                continue
            if href in vistos:
                continue
            vistos.add(href)
            links.append(href)
        return links

    def _extraer_articulo(self, url: str) -> dict | None:
        try:
            pag = StealthyFetcher.fetch(url, **FETCH_OPTS)
        except Exception:
            return None

        h1s = pag.css("h1")
        titulo = (h1s[0].get_all_text(strip=True) if h1s else "").strip()

        fecha = (pag.css("time::attr(datetime)").get() or pag.css("time::text").get() or "").strip()

        autor = (pag.css(".author-name::text, .blog-post-author a::text, a[rel='author']::text").get() or "").strip()

        parrafos = [
            t for p in pag.css("p")
            if len(t := _texto(p)) > 40 and not _es_basura(t)
        ]
        cuerpo = " ".join(dict.fromkeys(parrafos))

        from urllib.parse import urlparse
        raw_tags = pag.css("a[href*='/blog/tag/']::attr(href)").getall()
        tags = list(dict.fromkeys(
            urlparse(a).path.rstrip("/").split("/")[-1].replace("-", " ").title()
            for a in raw_tags if "/blog/tag/" in a
        ))

        if not titulo or not cuerpo:
            return None

        return {
            "titulo": titulo,
            "fecha": fecha,
            "autor": autor,
            "cuerpo": cuerpo,
            "tags": tags,
            "url": url,
            "fuente": self.name,
        }

    def start(self, skip_urls: set | None = None):
        if skip_urls is None:
            skip_urls = set()

        todas = []
        vistos_enlaces = set()
        for pagina in PAGINAS:
            enlaces = self._links(pagina)
            for e in enlaces:
                if e not in vistos_enlaces:
                    vistos_enlaces.add(e)
                    todas.append(e)

        nuevas = [u for u in todas if u not in skip_urls]

        items = []
        for url in nuevas[:MAX_ARTICULOS]:
            art = self._extraer_articulo(url)
            if art:
                items.append(art)
            if len(items) >= MAX_ARTICULOS:
                break

        return _Result(items)
