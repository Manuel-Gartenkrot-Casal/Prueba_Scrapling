from scrapling.fetchers import StealthyFetcher

# Usamos StealthyFetcher (camoufox) igual que el resto de los spiders: evita el
# bloqueo por JS de mundoaftermarket y no se cuelga. Bloqueamos recursos y
# evitamos network_idle para que cada página cargue en segundos.
# Antes este spider paginaba en loop (/page/N) y podía no terminar nunca; ahora
# tomamos solo la primera página y limitamos la cantidad de notas.
MAX_ARTICULOS = 3

# Parámetros comunes para todas las descargas: rápido y liviano en RAM.
FETCH_OPTS = {"headless": True, "disable_resources": True, "timeout": 25000}

BASURA = [
    "Un sitio multimedia integral",
    "corresponsales en Brasil y México",
    "Podes compartir esta nota",
    "activa JavaScript",
    "Nombre *",
    "Correo electrónico *",
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


class AftermarketSpider:
    """
    Scrapea la sección /mercado de Mundo Aftermarket.

    Listado: <h3><a href>titulo</a></h3>.
    """
    name = "aftermarket"
    start_url = "https://mundoaftermarket.com/mercado/"
    base = "https://mundoaftermarket.com"

    def start(self):
        portada = StealthyFetcher.fetch(self.start_url, **FETCH_OPTS)

        notas = []
        vistos = set()
        for href in portada.css("h3 a::attr(href)").getall():
            if not href or href in vistos:
                continue
            if href.startswith("/"):
                href = self.base + href
            vistos.add(href)
            notas.append(href)

        items = []
        for url in notas[:MAX_ARTICULOS]:
            titulo, bajada, cuerpo = "", "", ""
            try:
                pag = StealthyFetcher.fetch(url, **FETCH_OPTS)
                titulo = (pag.css("h1::text").get() or "").strip()
                bajada = (pag.css("h3::text").get() or "").strip()
                parrafos = [
                    t for p in pag.css("p")
                    if len(t := _texto(p)) > 30 and not _es_basura(t)
                ]
                cuerpo = " ".join(dict.fromkeys(parrafos))
            except Exception:
                pass

            items.append({
                "titulo": titulo,
                "bajada": bajada,
                "cuerpo": cuerpo,
                "url": url,
                "fuente": self.name,
            })

        return _Result(items)
