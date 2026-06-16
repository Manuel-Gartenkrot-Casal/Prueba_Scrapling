import os
import subprocess
import sys
import time
from flask import Flask, jsonify, Response, stream_with_context

from fuentes import cargar_fuentes, nombres_fuentes

app = Flask(__name__)

_TIMEOUT = 300  # 5 min por fuente


# ── Helpers: armar el comando para correr una fuente ──────────────────────────

def _cmd_fuente(nombre: str) -> list[str]:
    """Comando que corre el runner genérico para una fuente."""
    return ["run_fuente.py", nombre]


def run_script(args: list[str]) -> dict:
    """Corre `python <args...>` y captura toda la salida."""
    try:
        result = subprocess.run(
            [sys.executable, *args],
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
        return {"success": False, "output": "", "error": "Timeout: el proceso tardó más de 5 minutos."}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


def _stream_output(args: list[str]):
    """Corre `python <args...>` y produce su stdout línea por línea en tiempo real."""
    start = time.time()
    try:
        process = subprocess.Popen(
            [sys.executable, *args],
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


@app.route("/fuentes")
def fuentes():
    """Lista de fuentes configuradas, para que el frontend arme las tarjetas."""
    return jsonify([
        {"nombre": f["nombre"], "etiqueta": f.get("etiqueta", f["nombre"])}
        for f in cargar_fuentes()
    ])


@app.route("/run/<spider>", methods=["POST"])
def run(spider: str):
    if spider not in nombres_fuentes():
        return jsonify({"success": False, "error": f"La fuente '{spider}' no existe."}), 400
    result = run_script(_cmd_fuente(spider))
    status = 200 if result["success"] else 500
    return jsonify(result), status


@app.route("/run-all", methods=["POST"])
def run_all():
    """Corre todas las fuentes, una por una (secuencial a propósito)."""
    salidas = []
    ok_global = True
    for nombre in nombres_fuentes():
        r = run_script(_cmd_fuente(nombre))
        estado = "OK" if r["success"] else "ERROR"
        cuerpo = r["output"] if r["success"] else (r["error"] or r["output"])
        salidas.append(f"{'='*60}\n  {nombre.upper()}  [{estado}]\n{'='*60}\n{cuerpo}")
        if not r["success"]:
            ok_global = False
    return jsonify({"success": ok_global, "output": "\n\n".join(salidas)}), (200 if ok_global else 500)


@app.route("/generar", methods=["POST"])
def generar():
    result = run_script(["generar_articulo.py"])
    status = 200 if result["success"] else 500
    return jsonify(result), status


# ── Endpoints streaming (SSE) ─────────────────────────────────────────────────

@app.route("/stream/run/<spider>", methods=["POST"])
def stream_run(spider: str):
    if spider not in nombres_fuentes():
        return jsonify({"success": False, "error": f"La fuente '{spider}' no existe."}), 400
    return Response(
        stream_with_context(_stream_output(_cmd_fuente(spider))),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/stream/run-all", methods=["POST"])
def stream_run_all():
    def generate():
        for nombre in nombres_fuentes():
            yield f"\n{{{{SEPARADOR}}}}{nombre.upper()}{{{{SEPARADOR}}}}\n"
            yield from _stream_output(_cmd_fuente(nombre))
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/stream/generar", methods=["POST"])
def stream_generar():
    return Response(
        stream_with_context(_stream_output(["generar_articulo.py"])),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
