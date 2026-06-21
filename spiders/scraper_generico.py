import json
import re
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup
from scrapling.fetchers import StealthyFetcher
import trafilatura

FETCH_OPTS = {"headless": True, "disable_resources": True, "timeout": 25000}

_PAGINAS_SALTAR = ["login", "register", "search", "tag", "author", "category", "contact", "about", "privacy", "terms"]


class _Result:
    def __init__(self, items):
        self.items = items


def _fetch(url: str):
    """Fetch URL and return (pag_object, html_string)."""
    pag = StealthyFetcher.fetch(url, **FETCH_OPTS)
    if hasattr(pag, "body") and pag.body:
        raw = pag.body
        html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    elif hasattr(pag, "text") and pag.text:
        html = pag.text
    else:
        html = None
    return pag, html


def _extraer_titulo(html: str) -> str:
    """Extrae título del HTML cuando Trafilatura no lo encuentra."""
    soup = BeautifulSoup(html, "lxml")
    # Intentar h1
    h1 = soup.find("h1")
    if h1 and (t := h1.get_text(strip=True)):
        return t
    # Intentar og:title
    og = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if og and (c := og.get("content", "")):
        return c.strip()
    # Intentar title tag
    title = soup.find("title")
    if title and (t := title.get_text(strip=True)):
        return t
    return ""


def _extraer_articulo(html: str, url: str) -> dict | None:
    try:
        result = trafilatura.extract(html, output_format="json", url=url, include_links=False, include_images=False)
        if result:
            data = json.loads(result)
            titulo = (data.get("title") or "").strip() or _extraer_titulo(html)
            cuerpo = data.get("text") or ""
            fecha = data.get("date") or ""
            if titulo and cuerpo and len(cuerpo) > 100:
                return {"titulo": titulo, "cuerpo": cuerpo, "fecha": fecha, "url": url, "fuente": "custom"}
    except Exception:
        pass
    return None


_PATRON_FECHA = re.compile(r"/\d{4}/\d{2}/\d{2}/")


def _es_link_articulo(url: str, texto: str, dominio: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc != dominio:
        return False
    path = parsed.path.lower()
    if not path or path == "/":
        return False
    # Saltar páginas de author/login/etc
    if any(s in path for s in _PAGINAS_SALTAR if s in path):
        return False
    if any(url.endswith(ext) for ext in [".pdf", ".jpg", ".png", ".mp4", ".zip", ".xml", ".json"]):
        return False
    if len(texto) < 25:
        return False
    return True


def _encontrar_links(html: str, base_url: str) -> list[str]:
    dominio = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "lxml")
    vistos = set()
    articulos = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        texto = a.get_text(strip=True)
        url_completa = urljoin(base_url, href)

        if not href or not texto or url_completa in vistos:
            continue
        vistos.add(url_completa)
        if not _es_link_articulo(url_completa, texto, dominio):
            continue

        # Links con fecha en la URL (ej: /2025/11/17/) son casi siempre artículos
        prioridad = 0 if _PATRON_FECHA.search(url_completa) else 1
        articulos.append((prioridad, -len(texto), url_completa))

    # Ordenar: primero los que tienen fecha, luego por longitud de texto descendente
    articulos.sort()
    return [url for _, _, url in articulos]


def _procesar_individual(url: str, items: list):
    """Modo artículo individual: extrae solo la URL, sin buscar links."""
    print(f"\n>>> URL (individual): {url}")
    try:
        _, html = _fetch(url)
    except Exception as e:
        print(f"  [ERROR] No se pudo descargar: {e}")
        return
    if not html:
        print("  [ERROR] HTML vacío")
        return
    art = _extraer_articulo(html, url)
    if art:
        print(f"  \u2713 Artículo: {art['titulo'][:90]}")
        items.append(art)
    else:
        print("  \u2717 No se pudo extraer contenido del artículo")


def _procesar_listado(url: str, max_articulos: int, items: list):
    """Modo listado: busca links de artículos y extrae cada uno."""
    print(f"\n>>> URL (listado): {url}")
    try:
        _, html = _fetch(url)
    except Exception as e:
        print(f"  [ERROR] No se pudo descargar: {e}")
        return
    if not html:
        print("  [ERROR] HTML vacío")
        return
    enlaces = _encontrar_links(html, url)
    if not enlaces:
        print("  [ERROR] No se encontraron enlaces a artículos")
        return
    total = min(len(enlaces), max_articulos)
    print(f"  \u2192 {len(enlaces)} enlaces encontrados, procesando {total}...")
    for i, link in enumerate(enlaces[:max_articulos]):
        print(f"  [{i+1}/{total}] {link}")
        try:
            _, html_link = _fetch(link)
        except Exception as e:
            print(f"    [ERROR] {e}")
            continue
        if not html_link:
            continue
        art = _extraer_articulo(html_link, link)
        if art:
            print(f"    \u2713 {art['titulo'][:90]}")
            items.append(art)
        else:
            print("    \u2717 No se pudo extraer contenido")


def start(urls: list[str], max_articulos: int = 5, modo: str = "list") -> _Result:
    items = []
    for url in urls:
        if modo == "single":
            _procesar_individual(url, items)
        else:
            _procesar_listado(url, max_articulos, items)
    print(f"\n>>> Total artículos extraídos: {len(items)}")
    return _Result(items)
