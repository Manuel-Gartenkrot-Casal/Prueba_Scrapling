import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from db import db, col_trusted_urls, col_articulos, clasificar_y_guardar
from lm_studio import clasificar_articulo
from scraper import start

# Configuración por defecto
DEFAULT_INTERVAL_DAYS = 1

scheduler = BackgroundScheduler()

def run_trusted_scraping():
    print(f"[{datetime.datetime.now()}] Iniciando scraping automatizado de URLs confiables...")
    
    urls_confiables = list(col_trusted_urls.find({"estado": "activo"}))

    if not urls_confiables:
        print("No hay URLs confiables activas para procesar.")
        return

    print(f"Procesando {len(urls_confiables)} fuentes...")

    for doc in urls_confiables:
        url = doc["url"]
        print(f"Scrapeando: {url}")

        try:
            result = start([url], modo="list", max_articulos=10)
            items = result.items

            if items:
                res = clasificar_y_guardar(items, col_articulos, clasificar_articulo)
                print(f"  [OK] {res['aprobados']} nuevos artículos aprobados.")
            else:
                print(f"  [WARN] No se encontraron artículos nuevos en {url}")

            col_trusted_urls.update_one(
                {"url": url},
                {"$set": {"ultima_ejecucion": datetime.datetime.now(datetime.timezone.utc).isoformat()}}
            )
        except Exception as e:
            print(f"  [ERROR] Fallo al procesar {url}: {e}")

    print(f"[{datetime.datetime.now()}] Scraping automatizado finalizado.")

def start_scheduler(interval_days=DEFAULT_INTERVAL_DAYS):
    """Inicia el scheduler con el intervalo especificado."""
    # Eliminar trabajos previos si existen para evitar duplicados al reiniciar
    if scheduler.get_job("trusted_scraping"):
        scheduler.remove_job("trusted_scraping")
        
    scheduler.add_job(
        run_trusted_scraping, 
        "interval", 
        days=interval_days, 
        id="trusted_scraping",
        next_run_time=datetime.datetime.now() # Ejecutar inmediatamente al iniciar
    )
    scheduler.start()
    print(f"Scheduler iniciado. Ejecución cada {interval_days} día(s).")

def update_scheduler_interval(days: int):
    """Actualiza el intervalo de ejecución dinámicamente."""
    if scheduler.get_job("trusted_scraping"):
        scheduler.reschedule_job("trusted_scraping", trigger="interval", days=days)
        print(f"Intervalo actualizado a {days} día(s).")
    else:
        start_scheduler(days)

def get_next_execution():
    """Devuelve la próxima fecha de ejecución programada."""
    job = scheduler.get_job("trusted_scraping")
    if job:
        return job.next_run_time.isoformat()
    return None
