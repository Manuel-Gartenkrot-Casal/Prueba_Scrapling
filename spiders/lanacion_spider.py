from scrapling.fetchers import StealthyFetcher

# La Nacion aplica anti-bot: con Chromium normal (AsyncDynamicSession) la página
# nunca queda "idle" y el spider se cuelga hasta el timeout. StealthyFetcher
# (camoufox) devuelve el HTML real, igual que en ambito/cenital/perfil.
# Bloqueamos recursos y evitamos network_idle para que cada página cargue rápido.
MAX_ARTICULOS = 3

# Parámetros comunes para todas las descargas: rápido y liviano en RAM.
FETCH_OPTS = {"headless": True, "disable_resources": True, "timeout": 25000}

BASURA = [
    "Conforme a los criterios de",
    "Suscribite",
    "Newsletter",
    "Registrate",
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


class LanacionSpider:
    """
    Scrapea el buscador de "autopartes" en La Nacion.

    Listado: enlaces de resultados (tienen atributo onmousedown). Si ese selector
    no encuentra nada, cae a links de artículo que contienen "-nid".
    """
    name = "lanacion"
    start_url = "https://www.lanacion.com.ar/buscador/?query=autopartes"
    base = "https://www.lanacion.com.ar"

    def _links(self, portada):
        hrefs = portada.css("a[onmousedown]::attr(href)").getall()
        if not hrefs:
            hrefs = [h for h in portada.css("a::attr(href)").getall() if h and "-nid" in h]

        notas = []
        vistos = set()
        for href in hrefs:
            if not href:
                continue
            if href.startswith("/"):
                href = self.base + href
            if not href.startswith(self.base):
                continue
            if href in vistos:
                continue
            vistos.add(href)
            notas.append(href)
        return notas

    def start(self):
        portada = StealthyFetcher.fetch(self.start_url, **FETCH_OPTS)
        notas = self._links(portada)

        items = []
        for url in notas[:MAX_ARTICULOS]:
            titulo, fecha, cuerpo = "", "", ""
            try:
                pag = StealthyFetcher.fetch(url, **FETCH_OPTS)
                titulo = (pag.css("h1::text").get() or "").strip()
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
                "titulo": titulo,
                "fecha": fecha,
                "cuerpo": cuerpo,
                "url": url,
                "fuente": self.name,
            })

        return _Result(items)
