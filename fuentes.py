"""
fuentes.py

Punto único de configuración de las fuentes a scrapear. Lee fuentes.json y
expone helpers para el resto del proyecto (spiders, runner, Flask, generador).

Para agregar una fuente nueva NO hace falta tocar código: alcanza con sumar
una entrada en fuentes.json.
"""

import json
import os

_RUTA = os.path.join(os.path.dirname(__file__), "fuentes.json")


def cargar_fuentes() -> list[dict]:
    """Devuelve la lista de configuraciones de fuentes desde fuentes.json."""
    with open(_RUTA, encoding="utf-8") as f:
        return json.load(f)


def fuentes_por_nombre() -> dict[str, dict]:
    """Mapa {nombre: config} para acceso directo por nombre."""
    return {f["nombre"]: f for f in cargar_fuentes()}


def get_fuente(nombre: str) -> dict | None:
    """Devuelve la config de una fuente, o None si no existe."""
    return fuentes_por_nombre().get(nombre)


def nombres_fuentes() -> list[str]:
    """Lista de nombres de fuentes, en el orden de fuentes.json."""
    return [f["nombre"] for f in cargar_fuentes()]
