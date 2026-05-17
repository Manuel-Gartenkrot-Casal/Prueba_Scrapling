import subprocess
import sys
from flask import Flask, jsonify

app = Flask(__name__)

SPIDERS = {
    "lanacion":    "runlanacion.py",
    "aftermarket": "runaftermarket.py",
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


# Para agregar un spider nuevo:
#   1. Crear spiders/nuevo_spider.py
#   2. Crear runnuevo.py
#   3. Agregar a SPIDERS: "nombre": "runnuevo.py"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
