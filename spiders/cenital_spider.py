from scrapling.fetchers import StealthyFetcher

# StealthyFetcher (camoufox) es pesado. Bloqueamos recursos (imágenes, css,
# fuentes, video) y evitamos network_idle para que cada página cargue en
# segundos en vez de ~30s. Igual limitamos cuántas notas visitamos.
MAX_ARTICULOS = 3

# Parámetros comunes para todas las descargas: rápido y liviano en RAM.
FETCH_OPTS = {"headless": True, "disable_resources": True, "timeout": 25000}

BASURA = [
    "Suscribite",
    "Newsletter",
    "Registrate",
    "Seguinos",
    "Compartir",
]


class _Result:
    """Expone .items igual que los Spider del framework (lo usan los run*.py)."""
    def __init__(self, items):
        self.items = items


def _texto(elemento):
    if elemento is None:
        return ""
    return (elemento.get_all_text(strip=True) or "").strip()


def _es_basura(texto: str) -> bool:
    return any(b in texto for b in BASURA)


class CenitalSpider:
    """
    Scrapea los resultados de búsqueda de "autopartes" en Cenital (WordPress).

    Cenital aplica anti-bot, así que usamos StealthyFetcher (camoufox) para
    obtener el HTML real, tanto del listado como de cada nota.

    Listado: <article class="post"> con el primer <a href> como link y
    <h3 class="post__title"> como título.
    """
    name = "cenital"
    start_url = "https://cenital.com/?s=autopartes"
    base = "https://cenital.com"

    def start(self, skip_urls: set | None = None):
        if skip_urls is None:
            skip_urls = set()

        portada = StealthyFetcher.fetch(self.start_url, **FETCH_OPTS)

        # 1) Links + títulos del listado (uno por <article>)
        notas = []
        vistos = set()
        for art in portada.css("article"):
            href = art.css("a::attr(href)").get()
            titulo = (art.css("h3::text").get() or art.css("h2::text").get() or "").strip()
            if not href or not titulo:
                continue
            if href.startswith("/"):
                href = self.base + href
            if href in vistos:
                continue
            vistos.add(href)
            notas.append({"titulo": titulo, "url": href})

        # 2) Visitar cada nota y extraer el cuerpo. Si falla, igual guardamos
        #    título + url para no perder el artículo.
        items = []
        for nota in notas[:MAX_ARTICULOS]:
            if nota["url"] in skip_urls:
                continue
            fecha, cuerpo = "", ""
            try:
                pag = StealthyFetcher.fetch(nota["url"], **FETCH_OPTS)
                fecha = (
                    pag.css("time::attr(datetime)").get()
                    or pag.css("time::text").get()
                    or ""
                ).strip()
                parrafos = [
                    t for p in pag.css("p")
                    if len(t := _texto(p)) > 40 and not _es_basura(t)
                ]
                cuerpo = " ".join(dict.fromkeys(parrafos))
            except Exception:
                pass

            items.append({
                "titulo": nota["titulo"],
                "fecha": fecha,
                "cuerpo": cuerpo,
                "url": nota["url"],
                "fuente": self.name,
            })

        return _Result(items)
