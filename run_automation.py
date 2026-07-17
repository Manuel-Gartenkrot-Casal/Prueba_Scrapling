import sys
from scheduler import run_trusted_scraping, set_max_articulos

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            set_max_articulos(int(sys.argv[1]))
        except ValueError:
            pass
    run_trusted_scraping()
