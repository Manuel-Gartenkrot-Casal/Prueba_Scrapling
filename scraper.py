import json
import re
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup
from scrapling.fetchers import StealthyFetcher

FETCH_OPTS = {"headless": True, "disable_resources": True, "timeout": 10000}

_PAGINAS_SALTAR = [
    "login",
    "register",
    "search",
    "buscador",
    "tag",
    "author",
    "category",
    "contact",
    "about",
    "privacy",
    "terms",
    "moneda",
]

_PATRONES_NO_ARTICULO = re.compile(
    r"(buscador|/search|/busca|gsc\.|/tag/|/author/|/category/|/page/\d+|\.xml|\.json|\.rss|/feed|/login|/register|/contact|/about|/privacy|/terms|/wp-admin|/wp-login)",
    re.IGNORECASE,
)


class _Result:
    def __init__(self, items):
        self.items = items


def _es_url_util(url: str) -> tuple[bool, str]:
    """Valida si una URL es utilizable para scraping de artículos.
    Retorna (es_util, razon_si_no)."""
    parsed = urlparse(url)

    # Dominio vacío
    if not parsed.netloc:
        return False, "URL sin dominio"

    # Hash con parámetros de búsqueda de Google CSE
    if parsed.fragment and ("gsc." in parsed.fragment or "q=" in parsed.fragment):
        return False, "Es una página de búsqueda embebida (Google CSE)"

    # Query string con parámetros de búsqueda
    qs = parsed.query.lower()
    if "q=" in qs and ("buscador" in parsed.path.lower() or "/search" in parsed.path.lower()):
        return False, "Es una página de resultados de búsqueda"

    # Patrones que indican que no es un listado de artículos
    if _PATRONES_NO_ARTICULO.search(url):
        return False, "La URL coincide con un patrón no artístico (login, búsqueda, etc.)"

    # Archivos estáticos
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in [".pdf", ".jpg", ".png", ".mp4", ".zip", ".xml", ".json", ".css", ".js"]):
        return False, "Es un archivo estático, no una página de artículos"

    return True, "OK"


def _http_get(url: str, timeout: int = 15) -> str | None:
    """HTTP GET básico sin headless."""
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _fetch_wayback(url: str) -> str | None:
    """Fallback: obtener HTML desde Wayback Machine (Archive.org)."""
    for ano in ["2026", "2025", "2024"]:
        html = _http_get(f"https://web.archive.org/web/{ano}/{url}")
        if html and urlparse(url).path.rstrip("/").split("/")[-1] in html:
            return html
    return None


def _extraer_html(pag) -> str | None:
    """Extrae texto HTML de un objeto page de StealthyFetcher."""
    if hasattr(pag, "body") and pag.body:
        raw = pag.body
        return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    if hasattr(pag, "text") and pag.text:
        return pag.text
    return None


def _fetch(url: str):
    """Fetch URL y devuelve (pag_object, html_string).

    Estrategia: headless browser primero; si falla, Wayback Machine.
    """
    html = None
    pag = None

    # 1 — Headless browser (Playwright)
    try:
        pag = StealthyFetcher.fetch(url, **FETCH_OPTS)
        html = _extraer_html(pag)
    except Exception:
        pag = None

    if html:
        return pag, html

    # 2 — Fallback: Wayback Machine
    print("  [FALLBACK] Usando Wayback Machine...")
    html = _fetch_wayback(url)
    if html:
        return None, html

    return pag, html


def _extraer_titulo(html: str) -> str:
    """Extrae título del HTML cuando Trafilatura no lo encuentra."""
    soup = BeautifulSoup(html, "lxml")
    # og:title / twitter:title primero: es el título canónico del artículo y el
    # más fiable. El primer <h1> a veces es un widget o nombre de sección
    # (ej. Motor Show devuelve "Edição Da Semana" en el h1), por eso va después.
    og = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    if og and (c := og.get("content", "").strip()):
        return c
    # h1 como segunda opción
    h1 = soup.find("h1")
    if h1 and (t := h1.get_text(strip=True)):
        return t
    # <title> como último recurso (suele traer sufijo del sitio)
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
    if any(s in path for s in _PAGINAS_SALTAR):
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
    con_fecha = []
    sin_fecha = []

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
        if _PATRON_FECHA.search(url_completa):
            con_fecha.append(url_completa)
        else:
            sin_fecha.append(url_completa)

    # Orden DOM: primero los que tienen fecha, después el resto (mismo orden que en página)
    return con_fecha + sin_fecha


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
        print(f"  [OK] Artículo: {art['titulo'][:90]}")
        items.append(art)
    else:
        print("  [FAIL] No se pudo extraer contenido del artículo")


def _procesar_listado(url: str, max_articulos: int, items: list):
    """Modo listado: busca links de artículos y extrae cada uno."""
    # Validar URL antes de intentar scrapear
    es_util, razon = _es_url_util(url)
    if not es_util:
        print(f"\n>>> URL (listado): {url}")
        print(f"  [SKIP] URL no utilizable: {razon}")
        return

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
    print(f"  -> {len(enlaces)} enlaces encontrados, buscando {max_articulos} artículos...")
    for i, link in enumerate(enlaces):
        if len(items) >= max_articulos:
            break
        print(f"  [{i + 1}/{len(enlaces)}] {link}")
        try:
            _, html_link = _fetch(link)
        except Exception as e:
            print(f"    [ERROR] {e}")
            continue
        if not html_link:
            continue
        art = _extraer_articulo(html_link, link)
        if art:
            print(f"    [OK] {art['titulo'][:90]}")
            items.append(art)
        else:
            print("    [FAIL] No se pudo extraer contenido")


def start(urls: list[str], max_articulos: int = 5, modo: str = "list") -> _Result:
    items = []
    for url in urls:
        if modo == "single":
            _procesar_individual(url, items)
        else:
            _procesar_listado(url, max_articulos, items)
    print(f"\n>>> Total artículos extraídos: {len(items)}")
    return _Result(items)
