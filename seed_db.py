"""
seed_db.py — carga los JSON de la carpeta data/ a MongoDB.
Ejecutar una sola vez para migrar los datos existentes.
"""
import json
from db import col_lanacion, col_aftermarket, guardar_items

with open("data/autopartes.json", encoding="utf-8") as f:
    items_lanacion = json.load(f)

with open("data/aftermarket.json", encoding="utf-8") as f:
    items_aftermarket = json.load(f)

g1 = guardar_items(items_lanacion, col_lanacion)
print(f"La Nacion  → {len(items_lanacion)} artículos procesados, {g1} insertados/actualizados")

g2 = guardar_items(items_aftermarket, col_aftermarket)
print(f"Aftermarket → {len(items_aftermarket)} artículos procesados, {g2} insertados/actualizados")

print("\n✅ Seed completo.")
