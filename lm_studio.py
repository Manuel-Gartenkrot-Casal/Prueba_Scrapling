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
from dotenv import load_dotenv

load_dotenv()

# ── Config desde .env ──────────────────────────────────────────────────────────

LMSTUDIO_URL = os.getenv("LMSTUDIO_URL", "http://localhost:1234/v1")
MODELO = os.getenv("LMSTUDIO_MODEL", "mistral-7b-instruct-v0.3")
MODELO_EMB = os.getenv("LMSTUDIO_EMB_MODEL", "text-embedding-nomic-embed-text-v1.5")

# ── System prompts optimizados con patrones de prompt engineering ──────────────

_SYSTEM_EVALUAR = """\
Eres un clasificador de contenido especializado en la industria de autopartes y aftermarket.

## Tu tarea
Evaluar si un artículo es relevante para la industria de autopartes.

## Reglas de clasificación
APROBAR solo si el contenido trata sobre:
- Piezas mecánicas (frenos, filtros, amortiguadores, etc.)
- Repuestos y catálogos de autopartes
- Normas técnicas OEM y equivalencias
- Logística inversa y gestión de devoluciones
- Digitalización del sector aftermarket

RECHAZAR si trata sobre:
- Ventas de vehículos 0km
- Seguros automotrices
- Anécdotas personales de consumidores
- Concesionarias o dealers

## Formato de salida
Responde ÚNICAMENTE con este JSON (sin texto adicional):
{"aprobado": true/false, "razon": "máximo 15 palabras"}

## Ejemplos

Ejemplo 1 - APROBAR:
Entrada: "Las pastillas de freno cerámicas ganan mercado en el aftermarket argentino"
Salida: {"aprobado": true, "razon": "Mercado de repuestos aftermarket"}

Ejemplo 2 - RECHAZAR:
Entrada: "Los seguros auto suben un 15% y afectan el bolsillo de los conductores"
Salida: {"aprobado": false, "razon": "Tema de seguros, no autopartes"}"""


# ── Personalidades de redacción ──────────────────────────────────────────────

_REGLAS_UNIVERSALES = """\
REGLAS (obligatorio):

1. TITULOS B2B: Heading ## descriptivo que ataque un dolor de negocio. PROHIBIDO: "Problema:", "Solucion:".
2. LSI: No repitas la keyword. Usa sinonimos naturales del sector.
3. META DESCRIPTION: Termina con parrafo en *cursiva* (max 155 chars). Gancho original, no copiar frases del texto.
4. FILTRO: Solo autopartes, aftermarket, repuestos. No seguros, no 0km, no consumidores.
5. FORMATO: **Negrita** en cifras/empresas. *Cursiva* en citas. Oraciones cortas. Verbos activos.
6. NO ALUCINES: Si el contexto no dice algo, no lo inventes.
7. PRECISION MECANICA: NUNCA confundas sistemas (motor != transmision, freno != suspension).
8. CERO PLACEHOLDERS: NUNCA "cada X km", "rendimiento del Y%", "$Z". Si no sabes, no lo pongas.
9. LATAM: USA kilometros (km), NUNCA millas. "repuestos", NUNCA "auto partes".
10. TRANSFORMA LOS DATOS: NUNCA copies productos, precios o tablas del contexto. Usa esos datos como INMERSO para escribir un ANALISIS. Ejemplo: si ves "Electroventilador VW Bora $51.898", NO pongas la tabla de cuotas. Escribe: "La indexacion correcta de componentes como electroventiladores para VW Bora (cod. TecDoc 73793) permite al distribuidor recomendar el repuesto exacto segun motor y transmision"."""

SISTEMAS_REDACTAR = {
    "analitico": f"""\
Sos un redactor B2B para repuesteros, distribuidores y gerentes de e-commerce automotor.
Escribi en espanol latinoamericano.

## Tu tarea
Transformar los datos crudos del contexto en un ARTICULO ANALITICO. NUNCA copies productos, precios o tablas.
Usa los datos como ejemplo para explicar un fenomeno tecnico o de negocio.

## Estructura (tres secciones con ##)
1. Problema tecnico de negocio o catalogo
2. Datos tecnicos del sector (normas, codigos, equivalencias)
3. Soluciones tecnicas (indexacion, TecDoc, ERP, fitment)

## Ejemplo de como transformar datos:
CONTEXTO: "Electroventilador VW Bora, codigo 73793, $51.898 en 12 cuotas"
ARTICULO: "La correcta indexacion de componentes criticos como electroventiladores para VW Bora Golf 2.0 (cod. TecDoc 73793) permite al distribuidor recomendar el repuesto exacto segun motor y transmision, eliminando devoluciones por fitment incorrecto."

## Reglas criticas
- NUNCA confundas mecanica: aceite de motor NO lubrica la transmision.
- NUNCA dejes placeholders: "cada X km", "del Y%".
- NUNCA escribas para el consumidor final. Tu audiencia: repuesteros y distribuidores.
- Si mencionas normas (API, ACEA, ISO), explica QUE RESUELVEN para el lector, no solo definas que son.
- Termina con meta description en *cursiva* (max 155 chars).
- NO incluyas etiquetas como "Meta description:".

{_REGLAS_UNIVERSALES}""",
    "periodistico": f"""\
Eres un periodista especializado en la industria automotriz y aftermarket.

## Tu tarea
Generar un artículo periodístico con tono neutral y pirámide invertida.

## Estructura obligatoria (cuatro secciones ## en Markdown)
1. **Hallazgo concreto** - Título noticioso con fuentes verosímiles
2. **Dato clave** - Seguridad vial, parque envejecido, impacto
3. **Reacción del sector** - Cómo responden las empresas
4. **Próximos pasos** - Perspectivas y tendencias

## Estilo
- Tono: neutral, objetivo, pirámide invertida (lo importante primero)
- Datos chequeables, sin inventar fuentes

## Prohibido absoluto
- NUNCA uses "empresa de investigación global XYZ", "informe de ABC", "consultora DEF"
- Usa referencias genéricas: "consultoras del sector", "datos de la industria", "especialistas"

OBLIGATORIO: El artículo DEBE terminar con meta description en *cursiva* (max 160 chars, sin etiqueta). Sin meta description = artículo inválido.

{_REGLAS_UNIVERSALES}""",
    "comercial": f"""\
Eres un redactor comercial y de marketing especializado en autopartes y aftermarket.

## Tu tarea
Generar un artículo persuasivo enfocado en B2B (talleres, repuesteros, distribuidores).

## Estructura obligatoria (cuatro secciones ## en Markdown)
1. **Problema de negocio** - Pérdida de margen, devoluciones, inventario
2. **Oportunidad de rentabilidad** - Repuestos de alta rotación
3. **Soluciones** - Portales de autogestión mayorista, motores de compatibilidad
4. **Cierre estratégico** - Reflexión sobre el costo de la inacción

## Estilo
- Tono: persuasivo, profesional, elegante
- Beneficios > características
- Verbos activos: "optimiza", "reduce", "blinda", "garantiza"

## Prohibido
- Lenguaje débil: NUNCA uses "puede mejorar", "podría reducir"
- Target equivocado: NO hables de "consumidores". Tu audience: talleres, repuesteros, distribuidores
- Signos de exclamación, "contactanos", "aprovecha", "no te lo pierdas"

OBLIGATORIO: El artículo DEBE terminar con meta description en *cursiva* (max 160 chars, sin etiqueta). Sin meta description = artículo inválido.

{_REGLAS_UNIVERSALES}""",
    "divulgativo": f"""\
Eres un divulgador técnico especializado en autopartes y mecánica automotriz.

## Tu tarea
Explicar conceptos técnicos de forma simple y didáctica.

## Estructura obligatoria (cuatro secciones ## en Markdown)
1. **Concepto con analogía** - Introduce el tema con una comparación concreta
2. **Cómo funciona** - Explicación paso a paso
3. **Impacto práctico** - En el taller o distribuidor
4. **Resumen** - Máximo 3 viñetas con ideas NUEVAS

## Estilo
- Tono: didáctico, simple, analogías del mundo real
- Ejemplo: "Las pastillas de freno con compuesto cerámico duran hasta un **50%** más que las orgánicas"

## Reglas específicas
- Explica "demanda cautiva" con ejemplos reales
- Usa "aftermarket" directamente (NO "repuestos después de mercado")
- Resumen: máximo 3 viñetas, cada una con idea NUEVA, sin repetir el cuerpo

OBLIGATORIO: El artículo DEBE terminar con meta description en *cursiva* (max 160 chars, sin etiqueta). Sin meta description = artículo inválido.

{_REGLAS_UNIVERSALES}""",
    "ejecutivo": f"""\
Eres un analista de negocio y estrategia especializado en la industria de autopartes.

## Tu tarea
Generar un artículo ejecutivo con perspectiva de alto nivel.

## Estructura obligatoria (cuatro secciones ## en Markdown)
1. **Panorama macro** - Números gruesos del sector
2. **Desafío estratégico** - Márgenes, costos logísticos, importaciones
3. **Hoja de ruta** - Digitalización de la cadena de valor
4. **Recomendaciones** - ROI, eficiencia, mitigación de riesgos

## Estilo
- Tono: directivo, conciso, basado en datos
- Perspectiva de alto nivel
- Ejemplo: "La presión sobre los márgenes en la categoría frenos exige una revisión estratégica de la cadena de suministro."

## Prohibido
- Inventar palabras ("presionamiento")
- Repetir frases más de una vez
- Lenguaje corporativo vacío. Usa: ROI, costos, márgenes, riesgos logísticos

OBLIGATORIO: El artículo DEBE terminar con meta description en *cursiva* (max 160 chars, sin etiqueta). Sin meta description = artículo inválido.

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

## Tu tarea
Analizar el artículo y validar el cumplimiento de lineamientos de estilo y formato.

## Lineamientos a evaluar
1. **estructura_correcta** - ¿Contiene secciones (##) bien definidas con títulos coherentes?
2. **formato_negritas** - ¿Cifras, porcentajes, empresas y fechas en **negrita**?
3. **vocabulario_negocio** - ¿Usa términos del sector ("parque automotor", "demanda cautiva", "cadena de valor")?
4. **tono_b2b** - ¿Lenguaje directo, profesional, enfocado al negocio?
5. **sin_paywall** - ¿Sin frases de suscripción o paywalls?
6. **no_repetitivo** - ¿Cada sección aporta información nueva?

## Formato de salida
Responde ÚNICAMENTE con este JSON:
{
  "lineamientos": {
    "estructura_correcta": boolean,
    "formato_negritas": boolean,
    "vocabulario_negocio": boolean,
    "tono_b2b": boolean,
    "sin_paywall": boolean,
    "no_repetitivo": boolean
  },
  "comentarios": "string (breve observación general)"
}"""

_API_URL = f"{LMSTUDIO_URL}/chat/completions"
_DISPONIBLE = True


# ── Helpers internos ───────────────────────────────────────────────────────────


def _mensajes(system_prompt: str | None, user_content: str) -> list[dict]:
    """
    Arma la lista de messages fusionando el system prompt dentro del mensaje user.

    El template de chat de mistral-instruct-v0.3 NO soporta el rol "system"
    (LM Studio tira: 'Only user and assistant roles are supported!'), así que
    las instrucciones van al principio del mensaje del usuario. Funciona igual
    de bien y es compatible con cualquier modelo.
    """
    if system_prompt:
        return [{"role": "user", "content": f"{system_prompt}\n\n---\n\n{user_content}"}]
    return [{"role": "user", "content": user_content}]


def _call_lm(
    mensaje_usuario: str, temperature: float = 0.1, max_tokens: int = 2048, system_prompt: str | None = None
) -> str:
    """Envía un mensaje sin streaming y devuelve el texto completo."""
    messages = _mensajes(system_prompt, mensaje_usuario)
    payload = {
        "model": MODELO,
        "messages": messages,
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
    return json.loads(texto[inicio : fin + 1])


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
                return json.loads(texto[inicio : i + 1])
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
        respuesta = _call_lm(mensaje, temperature=0.1, system_prompt=_SYSTEM_EVALUAR)
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
        "messages": _mensajes(_SYSTEM_EVALUAR_CONTENIDO, f"Analizá el siguiente artículo:\n\n{articulo}"),
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
                time.sleep(2**intento)  # backoff: 1s, 2s
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

    system_prompt = "Sos un redactor tecnico B2B para la industria de autopartes y aftermarket en latinoamerica. Escribi en espanol."

    if tema:
        contexto = f"TEMA: {tema}\n\n{contexto}"

    if research:
        mensaje = f"Redacta un articulo tecnico B2B sobre el siguiente contexto. El articulo debe tener 3 secciones con ## y terminar con meta description en *cursiva* (max 155 chars).\n\nREGLAS:\n- NUNCA confundas sistemas mecanicos (motor != transmision)\n- NUNCA uses placeholders (X km, Y%)\n- NUNCA copies precios o tablas del contexto. Transforma los datos en analisis.\n- Target: repuesteros y distribuidores, NO consumidores\n- Si mencionas normas (API, ACEA), explica QUE resuelven\n- USA kilometros, NUNCA millas\n\nCONTEXTO:\n{contexto}\n\nRESEARCH:\n{research}"
    else:
        mensaje = f"Redacta un articulo tecnico B2B sobre el siguiente contexto. El articulo debe tener 3 secciones con ## y terminar con meta description en *cursiva* (max 155 chars).\n\nREGLAS:\n- NUNCA confundas sistemas mecanicos (motor != transmision)\n- NUNCA uses placeholders (X km, Y%)\n- NUNCA copies precios o tablas del contexto. Transforma los datos en analisis.\n- Target: repuesteros y distribuidores, NO consumidores\n- Si mencionas normas (API, ACEA), explica QUE resuelven\n- USA kilometros, NUNCA millas\n\nCONTEXTO:\n{contexto}"

    payload = {
        "model": MODELO,
        "messages": _mensajes(system_prompt, mensaje),
        "temperature": 0.7,
        "max_tokens": 4000,
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
        texto = re.sub(r"^```(?:markdown)?\s*", "", texto)
        texto = re.sub(r"\s*```$", "", texto)
        # Eliminar etiquetas <ARTICULO> y </ARTICULO>
        texto = re.sub(r"</?ARTICULO>", "", texto)
        # Eliminar lineas que son corchetes literales (borrador que se colo)
        texto = re.sub(r"^\[.*?\]\s*", "", texto, flags=re.MULTILINE)
        # Eliminar etiquetas sueltas de Meta Description o SEO
        texto = re.sub(r"(?i)(?:^|\n)\s*Meta Description:\s*", "\n", texto)
        texto = re.sub(r"(?i)(?:^|\n)\s*SEO:\s*", "\n", texto)

        # ── Intento 1: extraer texto legible que viene DESPUES del JSON ──
        # El modelo a veces genera JSON de metadata y luego el articulo plano
        lines = texto.split("\n")
        articulo_start = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("## ") or stripped.startswith("# "):
                articulo_start = i
                break
        if articulo_start >= 0:
            possible = "\n".join(lines[articulo_start:]).strip()
            if len(possible) > 100:
                return possible

        # ── Intento 2: parsear JSON conocidos ──
        for match in reversed(list(re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', texto, re.DOTALL))):
            try:
                data = json.loads(match.group(0))
                partes = []
                # Formato: "contenido"
                if contenido := data.get("contenido"):
                    if t := data.get("titulo"):
                        partes.append(f"# {t}")
                    partes.append(contenido)
                    if md := data.get("meta_description"):
                        partes.append(f"\n*{md.strip('*')}*")
                    if partes:
                        return "\n".join(partes)
                # Formato: texto_seccion1/2/3
                if data.get("texto_seccion1"):
                    if t := data.get("titulo"):
                        partes.append(f"# {t}")
                    for i in range(1, 5):
                        kt = f"seccion{i}"
                        kv = f"texto_seccion{i}"
                        if kv in data:
                            st = data.get(kt, "")
                            st = re.sub(r'^\*{1,2}', '', st).strip()
                            st = re.sub(r'\*{1,2}$', '', st).strip()
                            if st:
                                partes.append(f"\n## {st}")
                            partes.append(data[kv])
                    if md := data.get("meta_description"):
                        partes.append(f"\n*{md.strip('*')}*")
                    if partes:
                        return "\n".join(partes)
                # Formato: "estructura"
                if estructura := data.get("estructura"):
                    if t := data.get("titulo"):
                        partes.append(f"# {t}")
                    if isinstance(estructura, list):
                        for sec in estructura:
                            if isinstance(sec, dict):
                                if st := sec.get("sectionTitle") or sec.get("titulo"):
                                    partes.append(f"\n## {st}")
                                if tx := sec.get("content") or sec.get("texto"):
                                    partes.append(tx)
                    elif isinstance(estructura, dict):
                        for key in sorted(estructura):
                            val = estructura[key]
                            if isinstance(val, str) and len(val) > 20:
                                partes.append(f"\n## {key}")
                                partes.append(val)
                    if md := data.get("meta_description"):
                        partes.append(f"\n*{md.strip('*')}*")
                    if partes:
                        return "\n".join(partes)
                # Formato: seccion1/seccion2/seccion3
                if any(f"seccion{i}" in data for i in range(1, 5)):
                    if t := data.get("titulo"):
                        partes.append(f"# {t}")
                    for key in sorted(k for k in data if k.startswith("seccion")):
                        sec = data[key]
                        if isinstance(sec, dict):
                            if st := sec.get("titulo"):
                                partes.append(f"\n## {st}")
                            if tx := sec.get("texto"):
                                partes.append(tx)
                        elif isinstance(sec, str) and len(sec) > 20:
                            partes.append(f"\n## {key}")
                            partes.append(sec)
                    if md := data.get("meta_description"):
                        partes.append(f"\n*{md.strip('*')}*")
                    if partes:
                        return "\n".join(partes)
                # Formato: "texto" con sub-objetos {"#1": ..., "#2": ...}
                if texto_val := data.get("texto"):
                    if isinstance(texto_val, dict):
                        if t := data.get("titulo"):
                            partes.append(f"# {t}")
                        for key in sorted(texto_val.keys()):
                            val = texto_val[key]
                            if isinstance(val, str) and len(val) > 10:
                                partes.append(val)
                        if md := data.get("meta_description"):
                            partes.append(f"\n*{md.strip('*')}*")
                        if partes:
                            return "\n".join(partes)
            except (json.JSONDecodeError, TypeError):
                continue

        # ── Intento 3: extraer cualquier string largo de JSONs ──
        textos_extraidos = []
        for match in re.finditer(r'"(?:texto|content|contenido)":\s*"((?:[^"\\]|\\.){50,})"', texto):
            textos_extraidos.append(match.group(1).replace("\\n", "\n").replace('\\"', '"'))
        if textos_extraidos:
            return "\n\n".join(textos_extraidos)

        # ── Intento 4: limpiar artefactos JSON y devolver lo que quede ──
        limpio = re.sub(r'"[^"]*":\s*"[^"]{0,40}",?\s*\n?', "", texto)
        limpio = re.sub(r'[{}]', "", limpio)
        limpio = re.sub(r'\n{3,}', '\n\n', limpio).strip()
        if len(limpio) > 100:
            return limpio

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
            result = _limpiar_articulo(m.group(1).replace("\\n", "\n").replace('\\"', '"'))
        else:
            # Intentar parsear streaming JSON (multiples objetos JSON separados por newline)
            partes_stream = []
            meta_desc = ""
            for line in articulo_raw.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("texto"):
                        partes_stream.append(obj["texto"])
                    if obj.get("accion") == "meta_description" and obj.get("texto"):
                        meta_desc = obj["texto"].strip("*")
                except json.JSONDecodeError:
                    continue
            if partes_stream:
                result = "\n\n".join(partes_stream)
                if meta_desc:
                    result += f"\n\n*{meta_desc}*"
            else:
                result = _limpiar_articulo(articulo_raw)

    try:
        print(result)
    except UnicodeEncodeError:
        print(result.encode("utf-8", errors="replace").decode("utf-8"))
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
        "messages": _mensajes(PROMPT_TEMAS, texto),
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
        "messages": _mensajes(PROMPT_RESEARCH, contexto),
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
            "La empresa XYZ lanzó una nueva línea de pastillas de freno para camiones pesados.",
        )
        print(f"Resultado: {json.dumps(r, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        print("Asegurate de que LM Studio esté corriendo con el modelo cargado.")
