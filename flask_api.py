import json
import os
import subprocess
import sys
import time
from flask import Flask, jsonify, Response, request, stream_with_context

app = Flask(__name__)

SPIDERS = {
    "lanacion":    "runlanacion.py",
    "aftermarket": "runaftermarket.py",
    "ambito":      "runambito.py",
    "cenital":     "runcenital.py",
    "perfil":      "runperfil.py",
}

_TIMEOUT = 300  # 5 min por spider


# ── Helper: ejecutar script y capturar salida completa ────────────────────────

def run_spider(script: str, extra_args: list[str] | None = None) -> dict:
    cmd = [sys.executable, script] + (extra_args or [])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error":  result.stderr if result.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Timeout: el spider tardó más de 5 minutos."}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


# ── Helper: ejecutar script y transmitir salida línea por línea ────────────────

def _stream_output(script: str, extra_args: list[str] | None = None):
    """Ejecuta un script y produce su stdout línea por línea en tiempo real."""
    start = time.time()
    cmd = [sys.executable, script] + (extra_args or [])
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

        for line in process.stdout:
            if time.time() - start > _TIMEOUT:
                process.kill()
                yield "[TIME OUT] El proceso superó el límite de tiempo.\n"
                return
            yield line

        process.wait(timeout=5)
    except Exception as e:
        yield f"[ERROR] {e}\n"


# ── Endpoints clásicos (JSON, sin streaming) ──────────────────────────────────

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
    result = run_spider("generar_articulo.py")
    status = 200 if result["success"] else 500
    return jsonify(result), status


# ── Endpoints streaming (SSE) ─────────────────────────────────────────────────

@app.route("/stream/run/<spider>", methods=["POST"])
def stream_run(spider: str):
    if spider not in SPIDERS:
        return jsonify({"success": False, "error": f"Spider '{spider}' no existe."}), 400
    return Response(
        stream_with_context(_stream_output(SPIDERS[spider])),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/stream/run-all", methods=["POST"])
def stream_run_all():
    def generate():
        for nombre, script in SPIDERS.items():
            yield f"\n{{{{SEPARADOR}}}}{nombre.upper()}{{{{SEPARADOR}}}}\n"
            yield from _stream_output(script)
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/stream/generar", methods=["POST"])
def stream_generar():
    return Response(
        stream_with_context(_stream_output("generar_articulo.py")),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Endpoints para URLs custom ──────────────────────────────────────────────────

@app.route("/run-custom", methods=["POST"])
def run_custom():
    body = request.get_json(silent=True) or {}
    urls = body.get("urls", [])
    max_articulos = body.get("max", 5)
    if not urls:
        return jsonify({"success": False, "error": "Lista de URLs vacía."}), 400
    payload = json.dumps({"urls": urls, "max": max_articulos}, ensure_ascii=False)
    result = run_spider("runcustom.py", [payload])
    status = 200 if result["success"] else 500
    return jsonify(result), status


@app.route("/stream/run-custom", methods=["POST"])
def stream_run_custom():
    body = request.get_json(silent=True) or {}
    urls = body.get("urls", [])
    max_articulos = body.get("max", 5)
    if not urls:
        return jsonify({"success": False, "error": "Lista de URLs vacía."}), 400
    payload = json.dumps({"urls": urls, "max": max_articulos}, ensure_ascii=False)
    return Response(
        stream_with_context(_stream_output("runcustom.py", [payload])),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
