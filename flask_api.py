import os
import re
import subprocess
import sys
import threading
import time

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS

import scheduler
from db import col_articulos, db

app = Flask(__name__)
CORS(app)

_TIMEOUT = 1800  # 30 min (generación IA ~15-25 min en CPU)

# ── Helper: ejecutar script y capturar salida completa ────────────────────────


def run_script(script: str, extra_args: list[str] | None = None) -> dict:
    cmd = [sys.executable, script] + (extra_args or [])
    _LM_LOG = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\[(INFO|DEBUG|WARNING|ERROR|WARN)\]")
    _FILTERED_ERR_LOG = re.compile(r".*Channel Error.*", re.IGNORECASE)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        out_lines = [line for line in result.stdout.splitlines(True) if not _LM_LOG.match(line)]
        err_lines = [line for line in result.stderr.splitlines(True) if not _FILTERED_ERR_LOG.match(line)]
        return {
            "success": result.returncode == 0,
            "output": "".join(out_lines),
            "error": "".join(err_lines) if result.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Timeout: el proceso tardó más de 30 minutos."}
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

        _LM_LOG = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\[(INFO|DEBUG|WARNING|ERROR|WARN)\]")
        for line in process.stdout:
            if time.time() - start > _TIMEOUT:
                process.kill()
                yield "[TIME OUT] El proceso superó el límite de tiempo.\n"
                return
            if _LM_LOG.match(line):
                continue
            yield line

        process.wait(timeout=5)
    except Exception as e:
        yield f"[ERROR] {e}\n"


# ── Endpoints de Gestión de Datos ────────────────────────────────────────────────


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/check-volume", methods=["GET"])
def check_volume():
    keyword = request.args.get("keyword", "")
    if not keyword:
        return jsonify({"success": False, "error": "Se requiere el parámetro 'keyword'."}), 400

    try:
        count = col_articulos.count_documents({"$text": {"$search": keyword}})
        return jsonify({"success": True, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ── Endpoints de Generación ───────────────────────────────────────────────────────


@app.route("/ultimo-articulo", methods=["GET"])
def ultimo_articulo():
    col_generados = db["articulos_generados"]
    doc = col_generados.find_one({}, sort=[("generado_en", -1)])
    if not doc:
        return jsonify({"success": False, "error": "Todavía no hay artículos generados."}), 404
    return jsonify(
        {
            "success": True,
            "articulo": {
                "contenido": doc.get("contenido", ""),
                "tema": doc.get("tema", ""),
                "fuentes": doc.get("fuentes", []),
                "generado_en": doc.get("generado_en", ""),
                "docs_usados": doc.get("docs_usados", []),
            },
        }
    )


def _parse_request_args(body: dict) -> list[str]:
    """Extrae argumentos de tema/persona del request body."""
    args_list = []
    tema = body.get("tema", "").strip()
    persona = body.get("persona", "").strip()
    if tema:
        args_list.extend(["--tema", tema])
    if persona and persona in ("analitico", "periodistico", "comercial", "divulgativo", "ejecutivo"):
        args_list.extend(["--persona", persona])
    return args_list


@app.route("/generar", methods=["POST"])
def generar():
    body = request.get_json(silent=True) or {}
    args_list = _parse_request_args(body)
    result = run_script("generar_articulo.py", args_list)
    status = 200 if result["success"] else 500
    return jsonify(result), status


# ── Endpoints streaming (SSE) ─────────────────────────────────────────────────


@app.route("/stream/generar", methods=["POST"])
def stream_generar():
    body = request.get_json(silent=True) or {}
    args_list = _parse_request_args(body)
    return Response(
        stream_with_context(_stream_output("generar_articulo.py", args_list)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Endpoints para URLs Custom (Nuevas) ──────────────────────────────────────────


@app.route("/api/scraping-config", methods=["GET"])
def get_scraping_config():
    next_run = scheduler.get_next_execution()
    job = scheduler.scheduler.get_job("trusted_scraping")
    interval = job.trigger.interval.days if job else 1
    max_art = scheduler.get_max_articulos()

    return jsonify({"success": True, "interval_days": interval, "max_articulos": max_art, "next_execution": next_run})


@app.route("/api/scraping-config", methods=["POST"])
def set_scraping_config():
    body = request.get_json(silent=True) or {}
    days = body.get("interval_days")
    max_art = body.get("max_articulos")

    if days is not None:
        if not isinstance(days, int) or days < 1:
            return jsonify({"success": False, "error": "Se requiere 'interval_days' como un entero >= 1."}), 400
        scheduler.update_scheduler_interval(days)

    if max_art is not None:
        if not isinstance(max_art, int) or max_art < 1:
            return jsonify({"success": False, "error": "Se requiere 'max_articulos' como un entero >= 1."}), 400
        scheduler.set_max_articulos(max_art)

    msg_parts = []
    if days is not None:
        msg_parts.append(f"intervalo a {days} día(s)")
    if max_art is not None:
        msg_parts.append(f"max artículos a {max_art}")
    message = "Configuración actualizada: " + ", ".join(msg_parts) if msg_parts else "Sin cambios"

    return jsonify({"success": True, "message": message})


@app.route("/api/run-automation", methods=["POST"])
def run_automation():
    """Dispara la ejecución inmediata del scraping de URLs confiables."""
    try:
        max_art = scheduler.get_max_articulos()
        threading.Thread(target=lambda: _run_automation_thread(max_art)).start()
        return jsonify({"success": True, "message": "Scraping automatizado iniciado manualmente."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _run_automation_thread(max_art: int):
    from scheduler import set_max_articulos
    set_max_articulos(max_art)
    scheduler.run_trusted_scraping()


@app.route("/api/stream/run-automation", methods=["POST"])
def stream_run_automation():
    """Streaming SSE con el output en vivo del scraping de URLs confiables."""
    max_art = scheduler.get_max_articulos()
    return Response(
        stream_with_context(_stream_output("run_automation.py", [str(max_art)])),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/trusted-urls-stats", methods=["GET"])
def trusted_urls_stats():
    """Estadísticas de las URLs confiables y última ejecución."""
    try:
        total = db["trusted_urls"].count_documents({})
        activas = db["trusted_urls"].count_documents({"estado": "activo"})
        ultima = db["trusted_urls"].find_one({"ultima_ejecucion": {"$exists": True}}, sort=[("ultima_ejecucion", -1)])
        return jsonify(
            {
                "success": True,
                "total": total,
                "activas": activas,
                "ultima_ejecucion": ultima.get("ultima_ejecucion") if ultima else None,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/evaluate-article", methods=["POST"])
def evaluate_article():
    body = request.get_json(silent=True) or {}
    articulo = body.get("articulo", "")
    if not articulo:
        return jsonify({"success": False, "error": "Se requiere el contenido del artículo."}), 400

    # Si el articulo tiene wrapper JSON (ej: "articulo": "markdown..."), limpiarlo
    m = re.search(r'"articulo"\s*:\s*"(.+)"\s*}', articulo, re.DOTALL)
    if m:
        articulo = m.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
    articulo = articulo.lstrip("`").lstrip("markdown").strip()

    from lm_studio import evaluar_lineamientos

    resultado = evaluar_lineamientos(articulo)

    if "error" in resultado:
        return jsonify({"success": False, "error": resultado["error"]}), 500

    return jsonify({"success": True, "evaluation": resultado})


# ── Endpoint: Proveedores de IA ───────────────────────────────────────────────


@app.route("/api/providers", methods=["GET"])
def get_providers():
    """Estado actual del proveedor de IA y disponibilidad."""
    from lm_studio import verificar_provider

    return jsonify({"success": True, **verificar_provider()})


@app.route("/api/providers", methods=["POST"])
def set_provider():
    """Cambiar proveedor de IA (local / nvidia)."""
    body = request.get_json(silent=True) or {}
    provider = body.get("provider", "")
    if not provider:
        return jsonify({"success": False, "error": "Se requiere el campo 'provider'."}), 400

    from lm_studio import set_provider as _set_provider

    result = _set_provider(provider)
    status = 200 if result["success"] else 400
    return jsonify(result), status


@app.route("/api/suggested-urls", methods=["GET"])
def suggested_urls():
    try:
        docs = list(db["suggested_urls"].find().sort("fecha_sugerida", -1).limit(20))
        for d in docs:
            d["_id"] = str(d["_id"])
        return jsonify({"success": True, "urls": docs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/discover-sources", methods=["POST"])
def discover_sources():
    result = run_script("discover_sources.py")
    status = 200 if result["success"] else 500
    return jsonify(result), status


@app.route("/api/add-url", methods=["POST"])
def add_url():
    body = request.get_json(silent=True) or {}
    url = body.get("url", "")
    if not url:
        return jsonify({"success": False, "error": "Se requiere la URL."}), 400

    # Validacion rapida de URL antes de lanzar el script
    from scraper import _es_url_util
    es_util, razon = _es_url_util(url)
    if not es_util:
        return jsonify({
            "success": False,
            "error": f"URL no utilizable: {razon}. Use la URL directa de un articulo o de una pagina de listado."
        }), 400

    # Ejecutamos el nuevo script add_url.py
    result = run_script("add_url.py", [url])
    status = 200 if result["success"] else 500
    return jsonify(result), status


@app.route("/stream/add-url", methods=["POST"])
def stream_add_url():
    body = request.get_json(silent=True) or {}
    url = body.get("url", "")
    if not url:
        return jsonify({"success": False, "error": "Se requiere la URL."}), 400

    # Validacion rapida de URL antes de lanzar el script
    from scraper import _es_url_util
    es_util, razon = _es_url_util(url)
    if not es_util:
        return jsonify({
            "success": False,
            "error": f"URL no utilizable: {razon}. Use la URL directa de un articulo o de una pagina de listado."
        }), 400

    return Response(
        stream_with_context(_stream_output("add_url.py", [url])),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    # Iniciar el scheduler de scraping automático
    scheduler.start_scheduler()

    app.run(host="0.0.0.0", port=5000, threaded=True)
