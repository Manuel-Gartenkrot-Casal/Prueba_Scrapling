from pymongo import MongoClient

# Este link es el que copias de MongoDB
mi_link = "mongodb+srv://48792944_db_user:<db_password>@pruebascrapling.uo6x74d.mongodb.net/?appName=PruebaScrapling"

# Se lo pasas a Python para conectar
client = MongoClient(mi_link)
