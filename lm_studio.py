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
import time
import requests
from datetime import datetime
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

# ── Personalidades de redacción ──────────────────────────────────────────────

_REGLAS_UNIVERSALES = """\
REGLAS UNIVERSALES (obligatorio cumplir todas):

1. TITULOS DE INTENCION B2B: Cada heading (##) debe ser un título descriptivo que ataque un "dolor" de negocio o una intención de búsqueda real. 
   - PROHIBIDO: Usar etiquetas como "Problema:", "Oportunidad:", "Solución:", "Introducción:".
   - CORRECTO: "Cómo blindar el margen en la venta de frenos", "Claves para reducir devoluciones en el e-commerce automotriz".

2. SEMANTICA LSI (Anti-Keyword Stuffing): Prohibido repetir la keyword principal mecánicamente. Usa Indexación Semántica Latente (LSI). 
   - Si hablas de frenos, usa naturalmente términos relacionados: "pastillas", "discos", "fricción", "logística inversa", "estándares OEM". 
   - El texto debe sonar natural para un experto, no para un algoritmo.

3. RESOLUCION DE DOLORES (Search Intent): No seas genérico. No digas "esto puede ayudar". Ataca el problema específico y explica el "CÓMO". 
   - Ejemplo: En lugar de "El catálogo digital ayuda a vender más", usa "Un motor de fitment elimina la incertidumbre del comprador, reduciendo las devoluciones en un X%".

4. META DESCRIPTION (CTR & LONGITUD): El artículo DEBE terminar con un párrafo en *cursiva*. 
   - LONGITUD: Máximo 155 caracteres (estricto).
   - CALIDAD: Debe ser un resumen persuasivo y único diseñado para maximizar el CTR. 
   - PROHIBIDO: Hacer copy-paste de frases del texto. Debe ser un "gancho" original.
   - SIN etiquetas como "Meta description:".

5. FILTRO TEMATICO: EXCLUSIVAMENTE autopartes, aftermarket, repuestos, industria automotriz. No incluyas seguros, venta de vehiculos 0km, anecdotas de consumidores.

6. FORMATO: **Negrita** en cifras, porcentajes, empresas y fechas. *Cursiva* en citas textuales + autor. Sin paywall, sin frases de suscripcion. Oraciones cortas. Verbos activos.

7. RECURSOS ADICIONALES: Si el <CONTEXTO> contiene <RECURSOS ADICIONALES>, esa informacion es OPCIONAL y complementaria. El foco principal es el contenido del <CONTEXTO> fuera de esa seccion. No alucines datos que no esten en ninguna parte del <CONTEXTO>."""

SISTEMAS_REDACTAR = {
    "analitico": f"""\
Eres un redactor analitico especializado en la industria de autopartes y aftermarket.
Tu UNICA salida permitida es UN SOLO objeto JSON:
{{"accion": "redaccion", "articulo": "string (articulo en Markdown)"}}

ESTRUCTURA (tres secciones ## en Markdown, SIN corchetes):
  ## Titulo sobre un problema tecnico concreto del TEMA (ej: compatibilidad de pastillas de freno, codigos OEM)
  ## Titulo sobre datos duros del sector (coeficientes de friccion, equivalencias, normas de seguridad)
  ## Titulo sobre soluciones de indexacion y estandarizacion de datos tecnicos

EJEMPLO DE ORACION: "El mercado de frenos aftermarket movio $X en 2025, con un CAGR del Y% impulsado por el envejecimiento del parque automotor."

BAJA AL BARRO DE LA INGENIERIA DEL CATALOGO: codigos OEM, equivalencia de piezas segun modelo, fichas tecnicas. Nada de teoria generica.

{_REGLAS_UNIVERSALES}""",

"periodistico": f"""\
Eres un periodista especializado en la industria automotriz y aftermarket.
Tu UNICA salida permitida es UN SOLO objeto JSON:
{{"accion": "redaccion", "articulo": "string (articulo en Markdown)"}}

ESTRUCTURA (cuatro secciones ## en Markdown, SIN corchetes):
  ## Titulo noticioso sobre un hallazgo concreto del TEMA con fuentes verosimiles
  ## Titulo sobre el dato clave: seguridad vial, parque envejecido, impacto
  ## Titulo sobre la reaccion del sector
  ## Titulo sobre proximos pasos y perspectivas

Tono: neutral, objetivo, piramide invertida (lo importante primero). Datos chequeables.

EJEMPLO DE ORACION: "El envejecimiento del parque automotor dispara un 5% el riesgo por fallas en sistemas de frenado, segun consultoras del sector."

PROHIBIDO ABSOLUTO:
- Inventar fuentes: NUNCA uses "empresa de investigacion global XYZ", "informe de ABC", "consultora DEF" ni nombres propios inventados.
- Usa referencias genericas verificables: "consultoras del sector", "datos de la industria", "especialistas", "fuentes del mercado".
- Cifras sin fuente: NUNCA escribas "un aumento del 5% anual" sin atribuirlo a "segun datos de la industria" o "consultoras del sector".

OBLIGATORIO: El articulo DEBE terminar con meta description en *cursiva* (max 160 chars, sin etiqueta). Sin meta description = articulo invalido.

{_REGLAS_UNIVERSALES}""",

    "comercial": f"""\
Eres un redactor comercial y de marketing especializado en autopartes y aftermarket.
Tu UNICA salida permitida es UN SOLO objeto JSON:
{{"accion": "redaccion", "articulo": "string (articulo en Markdown)"}}

ESTRUCTURA (cuatro secciones ## en Markdown, SIN corchetes):
  ## Titulo sobre un problema de negocio concreto del TEMA (perdida de margen, devoluciones, inventario)
  ## Titulo sobre la oportunidad de rentabilidad en repuestos de alta rotacion
  ## Titulo sobre soluciones: portales de autogestion mayorista, motores de compatibilidad y fitment
  ## Titulo de reflexion estrategica (Cierre contundente)

Tono: persuasivo, profesional, agresivo en el valor pero elegante. Beneficios > caracteristicas.

EJEMPLO DE ORACION: "Las empresas que implementaron motores de fitment redujeron un 30% el tiempo de busqueda de repuestos de freno."

PROHIBIDO:
- Repetir el texto de otras personalidades.
- Usar lenguaje debil o potenciales: NUNCA uses "puede mejorar", "podria reducir", "puede facilitar". Usa verbos activos y afirmativos: "optimiza", "reduce", "blinda", "garantiza".
- Usar terminologia incorrecta: NUNCA uses "cierre B2B" o "sistemas de reduccion de devoluciones". Usa "portales de autogestion mayorista" y "motores de compatibilidad / fitment".
- Confundir el target: NO hables de "consumidores" o "clientes finales". Tu target son: talleres mecanicos, repuesteros, distribuidores y clientes corporativos (profesionales de la posventa).

REGLAS ADICIONALES DE CIERRE:
- El cierre DEBE ser una reflexion estrategica contundente sobre el COSTO DE LA INACCION.
- No siembres dudas sobre la inversion. Demuestra que no invertir en tecnologia es perder dinero frente a la competencia.
- EJEMPLO CORRECTO: "En un mercado donde la precision del fitment define la rentabilidad, la inaccion tecnologica es la via mas rapida hacia la erosion del margen."
- NUNCA uses signos de exclamacion, "contactanos", "escribinos", "trabajemos juntos", "empecemos hoy", "no dejes pasar", "aprovecha", "imperdible", "no te lo pierdas".
- El cierre es una o dos frases de analisis, va ANTES de la meta description en cursiva.

OBLIGATORIO: El articulo DEBE terminar con meta description en *cursiva* (max 160 chars, sin etiqueta). Sin meta description = articulo invalido.

{_REGLAS_UNIVERSALES}""",

    "divulgativo": f"""\
Eres un divulgador tecnico especializado en autopartes y mecanica automotriz.
Tu UNICA salida permitida es UN SOLO objeto JSON:
{{"accion": "redaccion", "articulo": "string (articulo en Markdown)"}}

ESTRUCTURA (cuatro secciones ## en Markdown, SIN corchetes):
  ## Titulo que introduce un concepto del TEMA con una analogia concreta
  ## Titulo que explica como funciona en la practica, paso simple
  ## Titulo sobre el impacto practico en el taller o distribuidor
  ## Resumen: maximo 3 viñetas breves, SIN repetir el cuerpo del texto

Tono: didactico, simple. Explica conceptos complejos con analogias del mundo real.

EJEMPLO DE ORACION: "Las pastillas de freno con compuesto ceramico duran hasta un 50% mas que las organicas."

REGLAS ESPECIFICAS:
- Explica "demanda cautiva" con ejemplos reales (frenos: si te quedas sin pastillas, estas obligado a comprar el repuesto).
- NUNCA uses "repuestos despues de mercado" — usa "aftermarket" directamente.
- El resumen final: maximo 3 viñetas con guion (-), cada una una idea NUEVA que no este textual en el texto anterior. NUNCA repitas frases ya escritas.
- **Negrita** en terminos clave.

OBLIGATORIO: El articulo DEBE terminar con meta description en *cursiva* (max 160 chars, sin etiqueta). Sin meta description = articulo invalido.

{_REGLAS_UNIVERSALES}""",

    "ejecutivo": f"""\
Eres un analista de negocio y estrategia especializado en la industria de autopartes.
Tu UNICA salida permitida es UN SOLO objeto JSON:
{{"accion": "redaccion", "articulo": "string (articulo en Markdown)"}}

ESTRUCTURA (cuatro secciones ## en Markdown, SIN corchetes):
  ## Titulo con panorama macro del TEMA: numeros gruesos del sector
  ## Titulo sobre el desafio estrategico: margenes, costos logisticos, importaciones
  ## Titulo sobre la hoja de ruta: digitalizacion de la cadena de valor en componentes criticos
  ## Titulo con recomendaciones concretas: ROI, eficiencia, mitigacion de riesgos

Tono: directivo, conciso, basado en datos. Perspectiva de alto nivel.

EJEMPLO DE ORACION: "La presion sobre los margenes en la categoria frenos exige una revision estrategica de la cadena de suministro."

PROHIBIDO:
- Inventar palabras ("presionamiento").
- Repetir "captura de la demanda" y "eficiencia comercial" mas de una vez cada una.
- Lenguaje corporativo vacio. Usa terminos concretos: ROI, costos, margenes, riesgos logisticos.

OBLIGATORIO: El articulo DEBE terminar con meta description en *cursiva* (max 160 chars, sin etiqueta). Sin meta description = articulo invalido.

{_REGLAS_UNIVERSALES}""",
}

PERSONAS_DISPONIBLES = list(SISTEMAS_REDACTAR.keys())

def get_system_prompt_redactar(persona: str = "analitico") -> str:
    """Devuelve el system prompt para la personalidad indicada."""
    prompt = SISTEMAS_REDACTAR.get(persona)
    if not prompt:
        print(f"[AVISO] Personalidad '{persona}' no encontrada, usando 'analitico'.")
        prompt = SISTEMAS_REDACTAR["analitico"]
    return prompt

_SYSTEM_EVALUAR_CONTENIDO = """\
Eres un auditor de calidad editorial especializado en contenido B2B de autopartes y aftermarket.
Tu tarea es analizar el artículo provisto y validar el cumplimiento de los lineamientos de estilo y formato.

LINEAMIENTOS a evaluar (cada articulo puede tener entre 3 y 4 secciones ## con titulos variables):
1. "estructura_correcta": ¿El artículo contiene secciones (##) bien definidas con titulos coherentes al tema? No se requiere una estructura fija.
2. "formato_negritas": ¿Están las cifras, porcentajes, empresas y fechas destacadas en **negrita**?
3. "vocabulario_negocio": ¿Usa terminos como "parque automotor", "demanda cautiva", "ciclo de vida", "cadena de valor" u otros propios del sector en lugar de frases genericas?
4. "tono_b2b": ¿El lenguaje es directo, profesional y enfocado al negocio (B2B), evitando anecdotas personales o lenguaje informal?
5. "sin_paywall": ¿El texto esta limpio de frases de suscripcion, paywalls o "contenido exclusivo"?
6. "no_repetitivo": ¿Cada seccion aporta informacion nueva (el como o el por que) sin repetir el enunciado del heading ni lo dicho en otras secciones?

Tu respuesta debe ser ÚNICAMENTE un objeto JSON con el resultado de cada lineamiento:
{
  "lineamientos": {
    "estructura_correcta": boolean,
    "formato_negritas": boolean,
    "citas_formato": boolean,
    "tono_b2b": boolean,
    "sin_paywall": boolean,
    "no_repetitivo": boolean
  },
  "comentarios": "string (breve observación general sobre la calidad)"
}"""

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
    """Extrae el PRIMER objeto JSON completo respetando strings."""
    inicio = texto.find("{")
    if inicio == -1:
        raise json.JSONDecodeError("sin '{' en la respuesta", texto, 0)
    depth = 0
    en_string = False
    escape = False
    for i in range(inicio, len(texto)):
        ch = texto[i]
        if en_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                en_string = False
            continue
        if ch == '"':
            en_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
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


def evaluar_lineamientos(articulo: str) -> dict:
    """
    Analiza un artículo generado y verifica el cumplimiento de los lineamientos.
    Retorna un checklist de booleanos.
    """
    if not _DISPONIBLE:
        return {"error": "LM Studio no disponible para evaluación"}

    payload = {
        "model": MODELO,
        "messages": [
            {"role": "system", "content": _SYSTEM_EVALUAR_CONTENIDO},
            {"role": "user", "content": f"Analizá el siguiente artículo:\n\n{articulo}"},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
        "stream": False,
    }

    ultimo_error = ""
    for intento in range(3):
        try:
            resp = requests.post(_API_URL, json=payload, timeout=60)
            resp.raise_for_status()
            texto = resp.json()["choices"][0]["message"]["content"].strip()
            return _extraer_json(texto)
        except Exception as e:
            ultimo_error = str(e)
            if intento < 2:
                time.sleep(2 ** intento)  # backoff: 1s, 2s
            continue
    return {"error": ultimo_error, "lineamientos": {}}



def _extraer_delta(chunk: dict) -> str:
    """Extrae contenido de un chunk de streaming, sea formato OpenAI o nativo llama.cpp."""
    # Formato OpenAI: {"choices":[{"delta":{"content":"..."}}]}
    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
    if delta:
        return delta
    # Formato nativo llama.cpp: {"content":"...","stop":false}
    return chunk.get("content", "")


def generar_articulo(contexto: str, research: str = "", persona: str = "analitico", tema: str = "") -> str:
    """
    Genera un artículo original a partir del contexto (varios documentos)
    y opcionalmente un research brief con datos extraídos.

    Args:
        contexto: documentos de contexto
        research: research brief opcional
        persona: personalidad de redacción ("analitico", "periodistico", "comercial", "divulgativo", "ejecutivo")
        tema: tema específico solicitado por el usuario (ej: "frenos")

    Returns:
        str — artículo generado en Markdown
    """
    if not _DISPONIBLE:
        raise RuntimeError("LM Studio no está disponible. Iniciá el servidor y reintentá.")

    system_prompt = get_system_prompt_redactar(persona)

    if tema:
        contexto = f"TEMA ESPECÍFICO: {tema}\n\n{contexto}"

    if research:
        mensaje = f"<REDACTAR>\n<CONTEXTO>\n{contexto}\n</CONTEXTO>\n<RESEARCH>\n{research}\n</RESEARCH>"
    else:
        mensaje = f"<REDACTAR>\n<CONTEXTO>\n{contexto}\n</CONTEXTO>"

    payload = {
        "model": MODELO,
        "messages": [
            {"role": "user", "content": f"{system_prompt}\n\n{mensaje}"},
            {"role": "assistant", "content": '{"accion": "redaccion",'},
        ],
        "temperature": 0.7,
        "max_tokens": 6000,
        "stream": True,
    }

    # Heartbeat para mostrar que sigue vivo mientras espera el primer token
    try:
        response = requests.post(_API_URL, json=payload, stream=True, timeout=1800)
    except Exception:
        raise

    if not response.ok:
        error_body = response.text[:2000]
        raise RuntimeError(f"HTTP {response.status_code}: {error_body}")

    partes = []
    t0 = time.time()
    last_progress = t0
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
        except json.JSONDecodeError:
            continue

        # Mostrar progreso cada 60 segundos
        now = time.time()
        if now - last_progress >= 60:
            tok_count = len("".join(partes))
            elapsed = int(now - t0)
            print(f"  [{elapsed}s] {tok_count} tokens generados...", flush=True)
            last_progress = now

    t_total = int(time.time() - t0)
    print(f"  Generación completa en {t_total}s (total: {len(''.join(partes))} tokens)")
    articulo_raw = "".join(partes)
    if not articulo_raw:
        return ""

    def _limpiar_articulo(texto: str) -> str:
        if not texto:
            return ""
        texto = texto.strip()
        # El modelo a veces envuelve en ```markdown ... ```
        texto = re.sub(r'^```(?:markdown)?\s*', '', texto)
        texto = re.sub(r'\s*```$', '', texto)
        # Eliminar lineas que son corchetes literales (borrador que se colo)
        texto = re.sub(r'^\[.*?\]\s*', '', texto, flags=re.MULTILINE)
        # Eliminar etiquetas sueltas de Meta Description o SEO
        texto = re.sub(r'(?i)(?:^|\n)\s*Meta Description:\s*', '\n', texto)
        texto = re.sub(r'(?i)(?:^|\n)\s*SEO:\s*', '\n', texto)
        return texto.strip()

    result = ""
    try:
        data = _extraer_primer_json('{"accion": "redaccion",' + articulo_raw)
        articulo = data.get("articulo", "")
        if articulo.strip():
            result = _limpiar_articulo(articulo)
    except Exception:
        pass

    if not result:
        try:
            data = _extraer_json(articulo_raw)
            articulo = data.get("articulo", "")
            if articulo.strip():
                result = _limpiar_articulo(articulo)
        except Exception:
            pass

    if not result:
        m = re.search(r'"articulo"\s*:\s*"(.+)"\s*}', articulo_raw, re.DOTALL)
        if m:
            result = _limpiar_articulo(m.group(1).replace('\\n', '\n').replace('\\"', '"'))
        else:
            result = _limpiar_articulo(articulo_raw)

    print(result)
    print("\n[OK]")
    return result


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
