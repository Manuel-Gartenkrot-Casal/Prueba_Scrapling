import datetime
import time
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from db import db

_DDG_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Palabras clave para filtrar resultados sin usar LM Studio
_KEYWORDS_NICHO = [
    "autopartes",
    "repuestos",
    "aftermarket",
    "automotriz",
    "taller mecanico",
    "talleres",
    "distribucion de respuestos",
    "frenos",
    "motor",
    "filtro",
    "amortiguador",
    "embrague",
    "pastillas de freno",
    "correa de distribucion",
    "bateria",
    "neumatico",
    "llanta",
    "escape",
    "radiador",
    "alternador",
    "bujia",
    "ignicion",
    "suspension",
    "direccion",
    "transmision",
    "cilindro",
    "piston",
    "valvula",
    "carburador",
    "inyector",
    "bomba de agua",
    "bomba de aceite",
    "compresor",
    "rodamiento",
    "reten",
    "junta",
    "tornilleria",
    "lubricante",
    "aceite motor",
    "refrigerante",
    "codigo de motor",
    "numero de parte",
    "OEM",
    "catalogo de respuestos",
    "manual de taller",
    "diagnostico automotriz",
    "escanner automotriz",
]

_MAX_RESULTS_POR_KEYWORD = 10
_MAX_SUGERENCIAS_TOTAL = 30


def _keywords_en_texto(texto: str) -> list[str]:
    texto_l = texto.lower()
    return [kw for kw in _KEYWORDS_NICHO if kw in texto_l]


def discover():
    print("Buscando nuevas fuentes de autopartes...")

    keywords_busqueda = [
        "noticias autopartes latinoamerica",
        "mercado de repuestos automotrices",
        "aftermarket automotor noticias",
        "distribucion de autopartes",
        "repuestos automotrices blog",
        "taller mecanico autopartes",
        "proveedores de autopartes",
        "catalogo de respuestos online",
    ]

    suggested_urls = []
    vistas = set()

    for kw in keywords_busqueda:
        print(f"\n--- Buscando: '{kw}' ---")
        try:
            resp = requests.post(
                _DDG_URL,
                data={"q": kw},
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"  [ERROR] busqueda DDG: {e}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        resultados = soup.select(".result")
        print(f"  {len(resultados)} resultados encontrados")

        for r in resultados:
            if len(suggested_urls) >= _MAX_SUGERENCIAS_TOTAL:
                break

            a = r.select_one("a.result__a")
            if not a:
                continue
            href = a.get("href", "")
            if "//duckduckgo.com/l/?uddg=" in href:
                parsed = urlparse(href)
                qs = parse_qs(parsed.query)
                href = qs.get("uddg", [""])[0]
            elif href.startswith("//"):
                href = "https:" + href
            if not href or not href.startswith("http"):
                continue

            if href in vistas:
                continue
            vistas.add(href)

            snippet_el = r.select_one(".result__snippet")
            titulo = a.get_text(strip=True)
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            texto_completo = f"{titulo} {snippet}"

            # Ver si ya esta en la base
            ya_existe = (
                db["trusted_urls"].find_one({"url": href})
                or db["suggested_urls"].find_one({"url": href})
                or db["articulos"].find_one({"url": href})
            )
            if ya_existe:
                print(f"  [SKIP] ya registrada: {href[:80]}")
                continue

            # Filtrar por keywords del nicho
            matches = _keywords_en_texto(texto_completo)
            if not matches:
                continue

            print(f"  [OK] {titulo[:70]}")
            suggested_urls.append(
                {
                    "url": href,
                    "titulo": titulo,
                    "snippet": snippet,
                    "keyword_match": matches,
                    "keyword_busqueda": kw,
                    "fecha_sugerida": datetime.datetime.now(datetime.UTC).isoformat(),
                }
            )

            time.sleep(0.3)

        if len(suggested_urls) >= _MAX_SUGERENCIAS_TOTAL:
            break

    if suggested_urls:
        db["suggested_urls"].insert_many(suggested_urls)
        print(f"\n[OK] {len(suggested_urls)} sugerencias guardadas en la base de datos.")
    else:
        print("\nNo se encontraron nuevas fuentes relevantes.")


if __name__ == "__main__":
    discover()
