"""
spiders/generic_spider.py

Spider genérico y configurable. En lugar de un archivo por sitio, lee la
configuración de cada fuente (URL, selectores, modo de listado, etc.) y scrapea
en base a eso. Para sumar una fuente nueva NO hay que escribir un spider: basta
con agregar una entrada en fuentes.json.

Todos los sitios de noticias argentinos que probamos aplican anti-bot, así que
usamos StealthyFetcher (camoufox). Bloqueamos recursos y evitamos network_idle
para que cada página cargue en segundos.

Dos modos de listado:

  "links"     → junta los href de un selector del listado, entra a cada nota y
                saca el título de la página del artículo (ej: La Nacion,
                Mundo Aftermarket).
  "articulos" → recorre bloques contenedores (ej. <article>) y saca link +
                título de cada bloque; después entra a cada nota por el cuerpo
                (ej: Ambito, Cenital, Perfil).
"""

from scrapling.fetchers import StealthyFetcher

# Parámetros comunes de descarga: rápido y liviano en RAM (sin network_idle).
FETCH_OPTS = {"headless": True, "disable_resources": True, "timeout": 25000}


class _Result:
    """Expone .items igual que los Spider originales (lo usa el runner)."""
    def __init__(self, items):
        self.items = items


def _texto(elemento) -> str:
    if elemento is None:
        return ""
    return (elemento.get_all_text(strip=True) or "").strip()


def _es_basura(texto: str, basura: list) -> bool:
    return any(b in texto for b in basura)


def _primero(elemento, selectores) -> str:
    """Prueba uno o varios selectores y devuelve el primer valor no vacío."""
    if not selectores:
        return ""
    if isinstance(selectores, str):
        selectores = [selectores]
    for sel in selectores:
        val = elemento.css(sel).get()
        if val and val.strip():
            return val.strip()
    return ""


def _normalizar(href: str, base: str):
    """Completa links relativos y descarta los que no son del mismo dominio."""
    if not href:
        return None
    href = href.strip()
    if href.startswith("/"):
        href = base + href
    if not href.startswith(base):
        return None
    return href


class GenericSpider:
    """Scrapea una fuente a partir de su configuración (dict de fuentes.json)."""

    def __init__(self, cfg: dict):
        self.cfg           = cfg
        self.nombre        = cfg["nombre"]
        self.base          = cfg["base"]
        self.start_url     = cfg["start_url"]
        self.modo          = cfg.get("modo", "articulos")
        self.max_articulos = cfg.get("max_articulos", 3)
        self.min_parrafo   = cfg.get("min_parrafo", 40)
        self.basura        = cfg.get("basura", [])
        self.sel           = cfg.get("selectores", {})
        self.cuerpo_sel    = self.sel.get("cuerpo", "p")

    # ── Listado ──────────────────────────────────────────────────────────────

    def _listar_modo_links(self, portada) -> list[dict]:
        """Junta href sueltos del listado. El título se saca después, de la nota."""
        link_sel = self.sel.get("link")
        hrefs = portada.css(link_sel).getall() if link_sel else []

        if not hrefs and self.sel.get("link_fallback"):
            contiene = self.sel.get("link_fallback_contiene")
            hrefs = [
                h for h in portada.css(self.sel["link_fallback"]).getall()
                if h and (contiene in h if contiene else True)
            ]

        notas, vistos = [], set()
        for href in hrefs:
            url = _normalizar(href, self.base)
            if not url or url in vistos:
                continue
            vistos.add(url)
            notas.append({"titulo": "", "url": url})
        return notas

    def _listar_modo_articulos(self, portada) -> list[dict]:
        """Recorre bloques contenedores y saca link + título de cada uno."""
        item_sel   = self.sel.get("item", "article")
        link_sel   = self.sel.get("link", "a::attr(href)")
        titulo_sel = self.sel.get("titulo", ["h3::text", "h2::text"])

        notas, vistos = [], set()
        for bloque in portada.css(item_sel):
            href   = bloque.css(link_sel).get()
            titulo = _primero(bloque, titulo_sel)
            if not href or not titulo:
                continue
            url = _normalizar(href, self.base)
            if not url or url in vistos:
                continue
            vistos.add(url)
            notas.append({"titulo": titulo, "url": url})
        return notas

    # ── Nota individual ──────────────────────────────────────────────────────

    def _extraer_nota(self, pag) -> dict:
        """Extrae fecha/bajada (si están configuradas) y el cuerpo de la nota."""
        datos = {}
        if "fecha" in self.sel:
            datos["fecha"] = _primero(pag, self.sel["fecha"])
        if "bajada" in self.sel:
            datos["bajada"] = _primero(pag, self.sel["bajada"])
        parrafos = [
            t for p in pag.css(self.cuerpo_sel)
            if len(t := _texto(p)) > self.min_parrafo and not _es_basura(t, self.basura)
        ]
        datos["cuerpo"] = " ".join(dict.fromkeys(parrafos))
        return datos

    # ── Orquestación ─────────────────────────────────────────────────────────

    def start(self) -> _Result:
        portada = StealthyFetcher.fetch(self.start_url, **FETCH_OPTS)

        if self.modo == "links":
            notas = self._listar_modo_links(portada)
        else:
            notas = self._listar_modo_articulos(portada)

        items = []
        for nota in notas[:self.max_articulos]:
            titulo = nota["titulo"]
            datos = {"cuerpo": ""}
            try:
                pag = StealthyFetcher.fetch(nota["url"], **FETCH_OPTS)
                datos = self._extraer_nota(pag)
                # En modo "links" el título sale de la página del artículo.
                if not titulo:
                    titulo = _primero(pag, self.sel.get("titulo", ["h1::text"]))
            except Exception:
                pass

            item = {
                "titulo": titulo,
                "cuerpo": datos.get("cuerpo", ""),
                "url":    nota["url"],
                "fuente": self.nombre,
            }
            if "fecha" in datos:
                item["fecha"] = datos["fecha"]
            if "bajada" in datos:
                item["bajada"] = datos["bajada"]
            items.append(item)

        return _Result(items)
