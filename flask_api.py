import subprocess
import sys
from flask import Flask, jsonify

app = Flask(__name__)

SPIDERS = {
    "lanacion":    "runlanacion.py",
    "aftermarket": "runaftermarket.py",
    "ambito":      "runambito.py",
    "cenital":     "runcenital.py",
    "perfil":      "runperfil.py",
}


def run_spider(script: str) -> dict:
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            timeout=600,  # 10 min máx por spider
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error":  result.stderr if result.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Timeout: el spider tardó más de 10 minutos."}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/run/<spider>", methods=["POST"])
def run(spider: str):
    if spider not in SPIDERS:
        return jsonify({"success": False, "error": f"Spider '{spider}' no existe."}), 400

    result = run_spider(SPIDERS[spider])
    status = 200 if result["success"] else 500
    return jsonify(result), status


@app.route("/run-all", methods=["POST"])
def run_all():
    """Corre todos los spiders en secuencia y junta la salida de cada uno."""
    salidas = []
    ok_global = True
    for nombre, script in SPIDERS.items():
        r = run_spider(script)
        estado = "OK" if r["success"] else "ERROR"
        cuerpo = r["output"] if r["success"] else (r["error"] or r["output"])
        salidas.append(f"{'='*60}\n  {nombre.upper()}  [{estado}]\n{'='*60}\n{cuerpo}")
        if not r["success"]:
            ok_global = False

    return jsonify({"success": ok_global, "output": "\n\n".join(salidas)}), (200 if ok_global else 500)


@app.route("/generar", methods=["POST"])
def generar():
    """Genera el artículo reescrito por la IA a partir de lo scrapeado."""
    result = run_spider("generar_articulo.py")
    status = 200 if result["success"] else 500
    return jsonify(result), status


# Para agregar un spider nuevo:
#   1. Crear spiders/nuevo_spider.py
#   2. Crear runnuevo.py
#   3. Agregar a SPIDERS: "nombre": "runnuevo.py"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
