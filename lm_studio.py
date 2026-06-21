"""
lm_studio.py

Cliente para LM Studio (API compatible con OpenAI).
Usa un único system prompt con dos modalidades vía etiquetas:

  <EVALUAR>  → clasifica artículos por relevancia + calidad
  <REDACTAR> → genera artículos originales a partir de contexto

Configuración vía .env:
  LMSTUDIO_URL    (default: http://localhost:1234/v1)
  LMSTUDIO_MODEL  (default: ai21-jamba-reasoning-3b)

Nota: usa requests directamente, sin el paquete openai.
"""

import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config desde .env ──────────────────────────────────────────────────────────

LMSTUDIO_URL   = os.getenv("LMSTUDIO_URL", "http://localhost:1234/v1")
MODELO         = os.getenv("LMSTUDIO_MODEL", "ai21-jamba-reasoning-3b")

# ── System prompt único (vos lo definiste) ─────────────────────────────────────

SYSTEM_PROMPT = """\
Eres un procesador de datos backend especializado en la industria de autopartes.
Tu ÚNICA salida permitida es un objeto JSON válido y estrictamente formateado.
REGLA CRÍTICA: NO incluyas saludos, explicaciones, introducciones, ni texto markdown fuera del JSON. Tu respuesta debe comenzar obligatoriamente con el carácter "{" y terminar con el carácter "}".

INSTRUCCIONES DE PROCESAMIENTO:

1. MODO EVALUACIÓN
Si el input contiene la etiqueta <EVALUAR>:
Determina si el texto está estrictamente relacionado con piezas mecánicas, repuestos o catálogos de autopartes. Rechaza cualquier texto sobre ventas de vehículos, seguros o anécdotas.
Debes devolver exactamente esta estructura:
{
  "accion": "evaluacion",
  "aprobado": boolean,
  "razon": "string (máximo 15 palabras con el motivo de aprobación/rechazo)"
}

2. MODO REDACCIÓN
Si el input contiene las etiquetas <REDACTAR> y <CONTEXTO>:
Escribe un artículo basándote ÚNICAMENTE en la información provista en el <CONTEXTO>. No agregues datos externos ni alucines especificaciones. Los documentos están ordenados del más reciente al más antiguo. Dale mayor peso a la información más reciente.
Debes devolver exactamente esta estructura:
{
  "accion": "redaccion",
  "articulo": "string (el artículo completo formateado en Markdown usando \\n para saltos de línea)"
}"""

_API_URL = f"{LMSTUDIO_URL}/chat/completions"
_DISPONIBLE = True


# ── Helpers internos ───────────────────────────────────────────────────────────

def _call_lm(mensaje_usuario: str, temperature: float = 0.1, max_tokens: int = 2048) -> str:
    """Envía un mensaje sin streaming y devuelve el texto completo."""
    payload = {
        "model": MODELO,
        "messages": [
            {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{mensaje_usuario}"},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    resp = requests.post(_API_URL, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def verificar_conexion() -> bool:
    """Verifica que LM Studio responda. Devuelve True si está disponible."""
    global _DISPONIBLE
    try:
        requests.get(f"{LMSTUDIO_URL}/models", timeout=5)
        _DISPONIBLE = True
    except Exception:
        _DISPONIBLE = False
        print(f"[AVISO] LM Studio ({LMSTUDIO_URL}) no disponible. Los artículos se guardarán sin filtrar.")
    return _DISPONIBLE


# ── API pública ────────────────────────────────────────────────────────────────

def clasificar_articulo(titulo: str, cuerpo: str) -> dict:
    """
    Evalúa si un artículo merece guardarse en la BD.

    Si LM Studio no está disponible, aprueba todo (modo degradado).

    Returns:
        {"aprobado": bool, "razon": str}
    """
    if not _DISPONIBLE:
        return {"aprobado": True, "razon": "modo degradado: LM Studio no disponible"}

    cuerpo_truncado = (cuerpo or "")[:2000]
    mensaje = f"<EVALUAR>\nTítulo: {titulo}\n\nCuerpo: {cuerpo_truncado}"

    try:
        respuesta = _call_lm(mensaje, temperature=0.1)
        data = json.loads(respuesta)
        return {
            "aprobado": data.get("aprobado", False),
            "razon": data.get("razon", "Sin razón especificada"),
        }
    except json.JSONDecodeError:
        return {"aprobado": False, "razon": "error: respuesta inválida del modelo"}
    except Exception as e:
        return {"aprobado": True, "razon": f"modo degradado: {str(e)}"}


def _extraer_delta(chunk: dict) -> str:
    """Extrae contenido de un chunk de streaming, sea formato OpenAI o nativo llama.cpp."""
    # Formato OpenAI: {"choices":[{"delta":{"content":"..."}}]}
    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
    if delta:
        return delta
    # Formato nativo llama.cpp: {"content":"...","stop":false}
    return chunk.get("content", "")


def generar_articulo(contexto: str) -> str:
    """
    Genera un artículo original a partir del contexto (varios documentos).

    Returns:
        str — artículo generado en Markdown
    """
    if not _DISPONIBLE:
        raise RuntimeError("LM Studio no está disponible. Iniciá el servidor y reintentá.")

    mensaje = f"<REDACTAR>\n<CONTEXTO>\n{contexto}\n</CONTEXTO>"

    payload = {
        "model": MODELO,
        "messages": [
            {"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{mensaje}"},
            {"role": "assistant", "content": '{"accion": "redaccion",'},
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True,
    }

    response = requests.post(_API_URL, json=payload, stream=True, timeout=180)
    if not response.ok:
        error_body = response.text[:2000]
        raise RuntimeError(f"HTTP {response.status_code}: {error_body}")

    partes = []
    for line in response.iter_lines():
        if not line:
            continue
        text = line.decode("utf-8")
        if text.startswith("data: "):
            text = text[6:]
        if text == "[DONE]":
            break
        try:
            chunk = json.loads(text)
            if "error" in chunk:
                print(f"\n[ERROR del modelo] {chunk.get('message', chunk['error'])}")
                continue
            delta = _extraer_delta(chunk)
            partes.append(delta)
            print(delta, end="", flush=True)
        except json.JSONDecodeError:
            continue

    print()
    articulo_raw = "".join(partes)
    if not articulo_raw:
        return ""

    try:
        data = json.loads('{"accion": "redaccion",' + articulo_raw)
        return data.get("articulo", articulo_raw)
    except json.JSONDecodeError:
        return articulo_raw


# ── Verificar conectividad al importar ────────────────────────────────────────

verificar_conexion()


# ── Test rápido (python lm_studio.py) ─────────────────────────────────────────

if __name__ == "__main__":
    print(f"🔌 Conectando a {LMSTUDIO_URL} con modelo {MODELO}...")
    try:
        r = clasificar_articulo(
            "Nueva línea de frenos para camiones",
            "La empresa XYZ lanzó una nueva línea de pastillas de freno para camiones pesados."
        )
        print(f"Resultado: {json.dumps(r, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        print("Asegurate de que LM Studio esté corriendo con el modelo cargado.")
