"""
lm_studio.py

Cliente para LM Studio (API compatible con OpenAI).
Usa dos system prompts separados (evaluación y redacción):

  <EVALUAR>  → clasifica artículos por relevancia + calidad
  <REDACTAR> → genera artículos originales a partir de contexto

Configuración vía .env:
  LMSTUDIO_URL    (default: http://localhost:1234/v1)
  LMSTUDIO_MODEL  (default: mistral-7b-instruct-v0.3)

Nota: usa requests directamente, sin el paquete openai.
"""

import json
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config desde .env ──────────────────────────────────────────────────────────

LMSTUDIO_URL   = os.getenv("LMSTUDIO_URL", "http://localhost:1234/v1")
MODELO         = os.getenv("LMSTUDIO_MODEL", "mistral-7b-instruct-v0.3")
MODELO_EMB     = os.getenv("LMSTUDIO_EMB_MODEL", "text-embedding-nomic-embed-text-v1.5")

# ── System prompt único (vos lo definiste) ─────────────────────────────────────

_SYSTEM_EVALUAR = """\
Eres un clasificador de contenido especializado en la industria de autopartes.
Tu ÚNICA salida permitida es un objeto JSON válido.
REGLA CRÍTICA: No incluyas texto fuera del JSON.

Si el input contiene <EVALUAR>:
Determina si el texto está estrictamente relacionado con piezas mecánicas, repuestos o catálogos de autopartes. Rechaza cualquier texto sobre ventas de vehículos, seguros o anécdotas.

Debes devolver exactamente:
{
  "accion": "evaluacion",
  "aprobado": boolean,
  "razon": "string (máximo 15 palabras)"
}"""

_SYSTEM_REDACTAR = """\
Eres un redactor especializado en la industria de autopartes y aftermarket.
Tu ÚNICA salida permitida es UN SOLO objeto JSON con esta estructura exacta:
{"accion": "redaccion", "articulo": "string (artículo en Markdown usando \\n para saltos de línea)"}

REGLA CRÍTICA: No incluyas evaluaciones, ni múltiples objetos JSON, ni texto fuera del JSON. Debes devolver un único objeto, no más.

Si el input contiene <REDACTAR>, <CONTEXTO> y <RESEARCH>:
Escribe un artículo de análisis del sector automotor / autopartes con estas secciones (## en Markdown):

  ## Introducción
  Arrancar con un hecho fuerte, dato concreto, oración corta. Sin rodeos. Una o dos líneas que enganchen al lector.

  ## La paradoja del repuesto
  Explicar que una alta circulación de autos usados es una **oportunidad** para el aftermarket (más vehículos en uso = más necesidad de mantenimiento y repuestos). El verdadero problema no es la demanda, sino la presión de costos locales frente a la oferta de importados y la falta de canales eficientes entre fabricantes, distribuidores y talleres.

  ## El contraataque digital
  Conectar los desafíos del sector con soluciones tecnológicas concretas: digitalización de catálogos y stock, fichas técnicas impecables, presencia en marketplaces, venta omnicanal. Mostrar que la ventaja competitiva ya no está solo en la fábrica, sino en la eficiencia comercial.

FILTRO TEMÁTICO: El artículo debe versar EXCLUSIVAMENTE sobre autopartes, aftermarket, repuestos, fabricación o digitalización del sector. No incluyas seguros, venta de vehículos 0km, anécdotas de consumidores, ni información no relacionada con autopartes.

REGLAS DE ESTILO:
- Oraciones cortas. Verbos activos. Lenguaje directo B2B.
- NO repitas información. Cada ejemplo debe conectar con la tesis de la sección.
- No alucines. Basate ÚNICAMENTE en el <CONTEXTO> y <RESEARCH>.
- NO incluyas frases de paywall, suscripción o "contenido exclusivo".
- Revisá ortografía y concordancia gramatical.
- Destacá en **negrita** cifras, porcentajes, empresas y fechas.
- Las citas textuales de ejecutivos en *cursiva* con el nombre del autor."""

_API_URL = f"{LMSTUDIO_URL}/chat/completions"
_DISPONIBLE = True


# ── Helpers internos ───────────────────────────────────────────────────────────

def _call_lm(mensaje_usuario: str, temperature: float = 0.1, max_tokens: int = 2048) -> str:
    """Envía un mensaje sin streaming y devuelve el texto completo."""
    payload = {
        "model": MODELO,
        "messages": [
            {"role": "user", "content": f"{_SYSTEM_EVALUAR}\n\n{mensaje_usuario}"},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    resp = requests.post(_API_URL, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _extraer_json(texto: str) -> dict:
    """
    Parsea el JSON de la respuesta del modelo de forma tolerante.

    Los modelos reasoning a veces anteponen un bloque <think>...</think>, fences
    markdown (```json) o prosa antes del objeto. En vez de exigir que TODA la
    respuesta sea JSON, quitamos ese ruido y tomamos del primer "{" al último "}".
    """
    # Quitar bloque de razonamiento <think>...</think>
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL)
    # Tomar del primer "{" al último "}" (descarta fences y prosa envolvente)
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio == -1 or fin == -1 or fin < inicio:
        raise json.JSONDecodeError("sin objeto JSON en la respuesta", texto, 0)
    return json.loads(texto[inicio:fin + 1])


def _extraer_primer_json(texto: str) -> dict:
    """Extrae el PRIMER objeto JSON completo. Si hay múltiples JSONs, descarta todo después del primero."""
    inicio = texto.find("{")
    if inicio == -1:
        raise json.JSONDecodeError("sin '{' en la respuesta", texto, 0)
    depth = 0
    for i in range(inicio, len(texto)):
        if texto[i] == "{":
            depth += 1
        elif texto[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(texto[inicio:i + 1])
    raise json.JSONDecodeError("JSON sin cerrar en la respuesta", texto, inicio)


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
        data = _extraer_json(respuesta)
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


def generar_articulo(contexto: str, research: str = "") -> str:
    """
    Genera un artículo original a partir del contexto (varios documentos)
    y opcionalmente un research brief con datos extraídos.

    Returns:
        str — artículo generado en Markdown
    """
    if not _DISPONIBLE:
        raise RuntimeError("LM Studio no está disponible. Iniciá el servidor y reintentá.")

    if research:
        mensaje = f"<REDACTAR>\n<CONTEXTO>\n{contexto}\n</CONTEXTO>\n<RESEARCH>\n{research}\n</RESEARCH>"
    else:
        mensaje = f"<REDACTAR>\n<CONTEXTO>\n{contexto}\n</CONTEXTO>"

    payload = {
        "model": MODELO,
        "messages": [
            {"role": "user", "content": f"{_SYSTEM_REDACTAR}\n\n{mensaje}"},
            {"role": "assistant", "content": '{"accion": "redaccion",'},
        ],
        "temperature": 0.7,
        "max_tokens": 6144,
        "stream": True,
    }

    response = requests.post(_API_URL, json=payload, stream=True, timeout=600)
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
        data = _extraer_primer_json('{"accion": "redaccion",' + articulo_raw)
        return data.get("articulo", articulo_raw)
    except json.JSONDecodeError:
        return articulo_raw


# ── Prompt para extracción de temas ────────────────────────────────────────────

PROMPT_TEMAS = """\
Analizá los siguientes artículos y extraé los 3 temas principales que se tratan.
Cada tema debe ser una frase corta de 2 a 5 palabras que capture el asunto central.
Tu respuesta debe comenzar con "{" y terminar con "}". No incluyas texto fuera del JSON.

Devolvé exactamente esta estructura:
{
  "temas": ["tema1", "tema2", "tema3"]
}"""


def extraer_temas(articulos: list[dict]) -> list[str]:
    if not articulos or not _DISPONIBLE:
        return ["autopartes aftermarket argentina"]

    texto = ""
    for i, doc in enumerate(articulos[:5], 1):
        titulo = doc.get("titulo", "(sin título)")
        cuerpo = doc.get("cuerpo", doc.get("bajada", ""))
        texto += f"Artículo {i}: {titulo}\n{cuerpo[:500]}\n\n"

    payload = {
        "model": MODELO,
        "messages": [{"role": "user", "content": f"{PROMPT_TEMAS}\n\n{texto}"}],
        "temperature": 0.3,
        "max_tokens": 512,
        "stream": False,
    }

    try:
        resp = requests.post(_API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data = _extraer_json(resp.json()["choices"][0]["message"]["content"])
        temas = data.get("temas", [])
        return temas[:3] if temas else ["autopartes aftermarket argentina"]
    except Exception:
        return ["autopartes aftermarket argentina"]


# ── Research pass ──────────────────────────────────────────────────────────────

PROMPT_RESEARCH = """\
Analizá el contexto provisto y extraé un research brief con TODOS los datos relevantes.
Incluí: nombres de empresas, nombres de ejecutivos con sus cargos, cifras exactas,
porcentajes, fechas, citas textuales entre comillas, y tendencias mencionadas.

Prestá atención especial a:
- Competencia de importados (China, Brasil) vs producción local de autopartes
- Oportunidades en el mercado de reposición / aftermarket (parque automotor usado)
- Desafíos de digitalización, e-commerce y catálogos digitales en el sector
- Costos locales vs internacionales y su impacto en competitividad
- Datos sobre marketplaces, venta online, omnicanalidad

Devolvé exactamente esta estructura JSON:
{
  "empresas": ["nombre1", "nombre2"],
  "ejecutivos": [{"nombre": "...", "cargo": "...", "cita": "..."}],
  "datos": [{"que": "...", "valor": "..."}],
  "tendencias": ["..."],
  "tema_principal": "..."
}"""


def research_contexto(contexto: str) -> str:
    if not _DISPONIBLE:
        return '{"empresas":[],"ejecutivos":[],"datos":[],"tendencias":[],"tema_principal":""}'

    payload = {
        "model": MODELO,
        "messages": [{"role": "user", "content": f"{PROMPT_RESEARCH}\n\n{contexto}"}],
        "temperature": 0.1,
        "max_tokens": 1024,
        "stream": False,
    }

    try:
        resp = requests.post(_API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        texto = resp.json()["choices"][0]["message"]["content"].strip()
        data = _extraer_json(texto)
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return '{"empresas":[],"ejecutivos":[],"datos":[],"tendencias":[],"tema_principal":""}'


# ── Embeddings ─────────────────────────────────────────────────────────────────

_EMB_URL = f"{LMSTUDIO_URL}/embeddings"


def calcular_embedding(texto: str) -> list[float] | None:
    """
    Devuelve el vector de embedding (significado) del texto, o None si falla.

    El vector se calcula UNA vez por artículo y se guarda en la BD; agrupar y
    comparar después es pura matemática (similitud coseno), sin volver a llamar
    al modelo. El modelo nomic admite ~8k tokens, truncamos por seguridad.
    """
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        resp = requests.post(
            _EMB_URL,
            json={"model": MODELO_EMB, "input": texto[:8000]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception as e:
        print(f"[AVISO] No se pudo calcular embedding: {e}. Verificá LMSTUDIO_EMB_MODEL en .env")
        return None


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
