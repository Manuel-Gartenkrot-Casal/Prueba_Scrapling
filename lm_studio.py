"""
lm_studio.py

Cliente unificado para LLM con soporte dual:
  - Local: LM Studio (API compatible con OpenAI)
  - Cloud: NVIDIA Build (API compatible con OpenAI)

Usa dos system prompts separados (evaluación y redacción):

  <EVALUAR>  → clasifica artículos por relevancia + calidad
  <REDACTAR> → genera artículos originales a partir de contexto

Configuración vía .env:
  AI_PROVIDER       (default: "local", opciones: "local", "nvidia")
  LMSTUDIO_URL      (default: http://localhost:1234/v1)
  LMSTUDIO_MODEL    (default: mistral-7b-instruct-v0.3)
  NVIDIA_API_KEY    (requerido para "nvidia")
  NVIDIA_BASE_URL   (default: https://integrate.api.nvidia.com/v1)
  NVIDIA_MODEL      (default: z-ai/glm-5.2)
  NVIDIA_EMB_MODEL  (default: nvidia/nv-embedqa-e5-v5)

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

# Proveedor activo
AI_PROVIDER = os.getenv("AI_PROVIDER", "local")

# LM Studio (local)
LMSTUDIO_URL = os.getenv("LMSTUDIO_URL", "http://localhost:1234/v1")
MODELO = os.getenv("LMSTUDIO_MODEL", "mistral-7b-instruct-v0.3")
MODELO_EMB = os.getenv("LMSTUDIO_EMB_MODEL", "text-embedding-nomic-embed-text-v1.5")

# NVIDIA Build (cloud)
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "z-ai/glm-5.2")
NVIDIA_EMB_MODEL = os.getenv("NVIDIA_EMB_MODEL", "nvidia/nv-embedqa-e5-v5")
NVIDIA_FALLBACK_MODEL = os.getenv("NVIDIA_FALLBACK_MODEL", "meta/llama-3.1-8b-instruct")

# ── System prompts optimizados con patrones de prompt engineering ──────────────

_SYSTEM_EVALUAR = """\
Eres un clasificador de contenido especializado en la industria de autopartes y aftermarket.

## Tu tarea
Evaluar si un articulo es relevante para la industria de autopartes.

## Reglas de clasificacion
APROBAR solo si el contenido trata sobre:
- Piezas mecanicas (frenos, filtros, amortiguadores, etc.)
- Repuestos y catalogos de autopartes
- Normas tecnicas OEM y equivalencias
- Logistica inversa y gestion de devoluciones
- Digitalizacion del sector aftermarket
- E-commerce B2B de repuestos
- Indexacion y fitment de componentes
- PAGINAS DE PRODUCTOS de repuestos (kits de distribucion, homocineticas, electroventiladores, espejos, botadores, pastillas, etc.)
- CATALOGOS de autopartes con precios y especificaciones tecnicas

RECHAZAR si trata sobre:
- Ventas de vehiculos 0km (concesionarias, agencias, listados de autos nuevos)
- Seguros automotrices
- Anecdotas personales de consumidores
- Concesionarias o dealers de VEHICULOS (no de repuestos)
- Contenido generico de B2C (explicar al consumidor basico)
- Contenido con alucinaciones tecnicas (conceptos inventados que no existen)

## IMPORTANTE: Diferenciar REPUSTOS de VEHICULOS
- "Kit Correa Distribucion Renault" = REPOSTO → APROBAR
- "Kit Homocinetica Chevrolet Corsa" = REPOSTO → APROBAR
- "Electroventilador VW Gol" = REPOSTO → APROBAR
- "Espejos Retrovisores" = REPOSTO → APROBAR
- "Botadores VW Amarok" = REPOSTO → APROBAR
- "Concesionaria Renault venta 0km" = VEHICULO → RECHAZAR
- "Review Toyota Corolla 2026" = VEHICULO → RECHAZAR

## Formato de salida
Responde UNICAMENTE con este JSON (sin texto adicional):
{"aprobado": true/false, "razon": "maximo 15 palabras"}

## Ejemplos

Ejemplo 1 - APROBAR:
Entrada: "Las pastillas de freno ceramicas ganan mercado en el aftermarket argentino"
Salida: {"aprobado": true, "razon": "Mercado de repuestos aftermarket"}

Ejemplo 2 - RECHAZAR:
Entrada: "Los seguros auto suben un 15% y afectan el bolsillo de los conductores"
Salida: {"aprobado": false, "razon": "Tema de seguros, no autopartes"}

Ejemplo 3 - RECHAZAR:
Entrada: "Las ruedas de traccion en dos ruedas son importantes para la seguridad"
Salida: {"aprobado": false, "razon": "Alucinacion tecnica: concepto inventado"}

Ejemplo 4 - APROBAR:
Entrada: "Kit Correa Distribucion Renault Master 2 2.5 G9u"
Salida: {"aprobado": true, "razon": "Repuesto Renault: kit distribucion"}

Ejemplo 5 - APROBAR:
Entrada: "Electroventilador P/ Gol Trend Voyage Fox Suran Todos C/aire"
Salida: {"aprobado": true, "razon": "Repuesto Volkswagen: electroventilador"}"""


# ── Personalidades de redacción ──────────────────────────────────────────────

_REGLAS_UNIVERSALES = """\
REGLAS (obligatorio):

1. TITULOS B2B: Heading ## descriptivo que ataque un dolor de negocio. PROHIBIDO: "Problema:", "Solucion:".
2. LSI: No repitas la keyword. Usa sinonimos naturales del sector.
3. META DESCRIPTION: Termina con parrafo en *cursiva* (max 155 chars). Gancho original, no copiar frases del texto.
4. FILTRO: Solo autopartes, aftermarket, repuestos. No seguros, no 0km, no consumidores.
5. FORMATO: **Negrita** en cifras/empresas. *Cursiva* en citas. Oraciones cortas. Verbos activos.
6. NO ALUCINES: Si el contexto no dice algo, no lo inventes. NUNCA inventes categorias de productos que no existen (ej: "ruedas de traccion en dos ruedas" NO EXISTE).
7. PRECISION MECANICA: NUNCA confundas sistemas (motor != transmision, freno != suspension).
8. CERO PLACEHOLDERS: NUNCA "cada X km", "rendimiento del Y%", "$Z". Si no sabes, no lo pongas.
9. LATAM: USA kilometros (km), NUNCA millas. "repuestos", NUNCA "auto partes".
10. TRANSFORMA LOS DATOS: NUNCA copies productos, precios o tablas del contexto. Usa esos datos como INMERSO para escribir un ANALISIS.
11. TERMINOLOGIA EXACTA: neumaticos/cubiertas (goma), llantas (aleacion/chapa), pastillas de freno (no "pastillas de seguridad"). NUNCA mezcles terminos de componentes diferentes.
12. SUJETO CORRECTO: Cuando hablas de degradacion, desgaste, reseca o perdida de elasticidad, el sujeto es el NEUMATICO (caucho), NUNCA la rueda. La rueda NO tiene propiedades elasticas. Ejemplo CORRECTO: "Un lote de neumaticos que supera 36 meses..." Ejemplo INCORRECTO: "Un lote de ruedas que supera 36 meses..."
13. CERO OBVEDADES: Tu lector es un repuestero o distribuidor. NO le expliques que "los frenos son importantes" o que "hay que elegir la medida correcta". El ya lo sabe. Entra directo al dolor tecnico o comercial.
14. SIN REPETICIONES: NUNCA repitas la misma frase en el articulo, especialmente en conclusiones. Si ya dijiste algo, no lo vuelvas a pegar.
15. B2B PURO: Tu audiencia NO es el conductor. Es el tallerista, el distribuidor, el gerente de e-commerce. NO le expliques al lector que "debe considerar la velocidad y el peso del vehiculo". Eso ya lo sabe. Habla de MARGENES, ROTACION, DEVOLUCIONES, INDEXACION, ERP, FITMENT.
16. PLATAFORMAS REALES: Si el contexto menciona empresas o plataformas (Alephee, Mercado Libre, TecDoc, eBay Motors, Amazon Automotive), MENCIONALAS por nombre. NO las-generalices como "una plataforma" o "un marketplace".
17. CTA OBLIGATORIO: El articulo DEBE terminar con una llamada a la accion (CTA). Ejemplo: "Descubre como...", "Conoce mas sobre...", "Transforma tu...". Sin CTA = articulo invalido.
18. ESTRUCTURA ALEPHEE: Articulos estilo blog B2B: titulo descriptivo, introduccion con gancho, secciones con ##, viñetas para ventajas/datos, datos especificos (empresas, tiendas, porcentajes), cierre con CTA.
19. DATOS REALES: NUNCA inventes estadisticas, porcentajes o cifras. Si el contexto no dice "70%", NO pongas "70%". Usa datos SOLO si aparecen en el contexto.
20. ORTOGRAFIA: Escribe con tildes y puntuacion correctas. "tecnologia" NO, "tecnologia" SI. "region" NO, "region" SI. "traves" NO, "traves" SI."""

SISTEMAS_REDACTAR = {
    "analitico": f"""\
Sos un redactor B2B para repuesteros, distribuidores y gerentes de e-commerce automotor.
Escribi en espanol latinoamericano.

## Tu tarea
Transformar los datos crudos del contexto en un ARTICULO ANALITICO estilo blog B2B. NUNCA copies productos, precios o tablas.
Usa los datos como ejemplo para explicar un fenomeno tecnico o de negocio del sector aftermarket.

## Contexto del sector
Tu audiencia son: repuesteros, distribuidores, gerentes de e-commerce automotor, talleres multimarca.
Ellos necesitan: aumentar rotacion, reducir devoluciones, mejorar indexacion, integrar con marketplaces.
Plataformas clave: Alephee (e-commerce B2B), Mercado Libre (marketplace), TecDoc (catalogo de referencias cruzadas), catalogacion digital, tiendas oficiales multivendedor.

## Estructura obligatoria (cuatro secciones ## en Markdown)
1. **Dato concreto o tendencia** - Abre con un numero o tendencia del sector e-commerce automotor
2. **Analisis del fenomeno** - Explica POR QUE ocurre, con datos tecnicos del sector
3. **Impacto en el negocio** - Como afecta a distribuidores/repuesteros
4. **Soluciones o tendencias** - Que pueden hacer, con ejemplos de plataformas reales

## Ejemplo de como transformar datos:
CONTEXTO: "Electroventilador VW Bora, codigo 73793, $51.898 en 12 cuotas"
ARTICULO: "La correcta indexacion de componentes criticos como electroventiladores para VW Bora Golf 2.0 (cod. TecDoc 73793) permite al distribuidor recomendar el repuesto exacto segun motor y transmision, eliminando devoluciones por fitment incorrecto."

## Reglas criticas
- NUNCA confundas mecanica: aceite de motor NO lubrica la transmision.
- NUNCA dejes placeholders: "cada X km", "del Y%".
- NUNCA escribas para el consumidor final. Tu audiencia: repuesteros y distribuidores.
- Si mencionas normas (API, ACEA, ISO), explica QUE RESUELVEN para el lector, no solo definas que son.
- NUNCA inventes conceptos tecnicos que no existen.
- NO expliques obviedades al lector (ej: "los frenos son importantes").
- TERMINOLOGIA EXACTA: neumaticos/cubiertas (goma), llantas (aleacion). NUNCA mezcles.
- Sin repeticiones en conclusiones.
- Menciona plataformas reales si el contexto las incluye (Alephee, Mercado Libre, TecDoc).
- Termina con meta description en *cursiva* (max 155 chars).
- NO incluyas etiquetas como "Meta description:".
- CTA: El articulo DEBE terminar con una llamada a la accion.

{_REGLAS_UNIVERSALES}""",
    "periodistico": f"""\
Eres un periodista especializado en la industria automotriz y aftermarket en Latinoamerica.

## Tu tarea
Generar un articulo periodistico estilo blog B2B con tono neutral y piramide invertida.

## Contexto del sector
Tu audiencia son: repuesteros, distribuidores, gerentes de e-commerce automotor.
Ellos necesitan: informacion sobre tendencias del sector, casos de exito, novedades de plataformas.
Plataformas clave: Alephee (e-commerce B2B), Mercado Libre (marketplace), TecDoc (catalogo de referencias cruzadas).

## Estructura obligatoria (cuatro secciones ## en Markdown)
1. **Hallazgo concreto** - Titulo noticioso con datos verosimiles del sector
2. **Dato clave** - Numeros del mercado, tendencias de e-commerce, impacto en el sector
3. **Reaccion del sector** - Como responden las empresas, distribuidores, marcas
4. **Proximos pasos + CTA** - Perspectivas y tendencias + llamada a la accion

## Estilo
- Tono: neutral, objetivo, piramide invertida (lo importante primero)
- Datos chequeables, sin inventar fuentes
- Menciona empresas y plataformas reales del contexto

## Prohibido absoluto
- NUNCA uses "empresa de investigacion global XYZ", "informe de ABC", "consultora DEF"
- Usa referencias genericas: "consultoras del sector", "datos de la industria", "especialistas"
- NUNCA inventes conceptos tecnicos que no existen.
- NO expliques obviedades al lector B2B.
- Sin repeticiones en conclusiones.
- TERMINOLOGIA EXACTA: neumaticos/cubiertas (goma), llantas (aleacion). NUNCA mezcles.
- GENERALIZAR PLATAFORMAS: Si el contexto menciona Alephee, Mercado Libre, TecDoc, etc., MENCIONALAS por nombre.

OBLIGATORIO: El articulo DEBE terminar con meta description en *cursiva* (max 155 chars, sin etiqueta) + CTA. Sin meta description = articulo invalido.

{_REGLAS_UNIVERSALES}""",
    "comercial": f"""\
Eres un redactor comercial B2B para la industria de autopartes y aftermarket en Latinoamerica.

## Tu tarea
Generar un articulo estilo blog B2B que VENDA una solucion tecnica o comercial para el sector autopartista. NO describas el problema: VENDE la resolucion.

## Contexto del sector
Tu audiencia son: repuesteros, distribuidores, gerentes de e-commerce automotor, talleres multimarca.
Ellos necesitan: aumentar rotacion, reducir devoluciones, mejorar indexacion, integrar con marketplaces.
Plataformas clave: Alephee (e-commerce B2B), Mercado Libre (marketplace), TecDoc (catalogo de referencias cruzadas), catalogacion digital, tiendas oficiales multivendedor.

## Estructura obligatoria (cuatro secciones ## en Markdown)
1. **Gancho con dato real** (1 parrafo) - Abre con un dato CONCRETO del contexto (NO inventado). Si no hay dato real, usa una tendencia del sector sin porcentajes inventados.
2. **La solucion concreta** (2-3 parrafos) - QUE HACE la herramienta/plataforma/producto para resolverlo. Datos especificos del contexto. Menciona plataformas reales si el contexto las incluye.
3. **Casos de exito reales** - Usa SOLO empresas y casos mencionados en el contexto. NO inventes casos. Si el contexto menciona Bridgestone, Volkswagen, Renault, etc., usa esos datos reales.
4. **CTA + meta description** - Cierre con llamada a la accion en PRESENTE (no infinitivo) + meta description en *cursiva* (max 155 chars).

## Ejemplo de articulo estilo Alephee (CORRECTO):
## Neumaticos Premium y UHP: el desafio de digitalizar la alta gama en el aftermarket

La venta de neumaticos de Ultra Alto Rendimiento (UHP) y de gama premium representa uno de los segmentos mas rentables y, a la vez, mas exigentes de la posventa automotriz. El cliente que adquiere este tipo de componentes no solo busca un producto que cumpla con los estandares maximos de adherencia y velocidad; exige una experiencia de compra impecable, donde la precision tecnica del catalogo y el servicio de instalacion fisica en el taller esten perfectamente sincronizados.

## La estrategia de Bridgestone: Sincronizacion de catalogo y capilaridad fisica

En este escenario de alta exigencia, la digitalizacion de la cadena de valor dejo de ser un proyecto a futuro para convertirse en el motor del negocio actual. Bridgestone implemento la suite tecnologica de Alephee para centralizar y gestionar su catalogo digital de productos de forma automatizada.

Esta infraestructura permite que el inventario disponible de neumaticos premium se sincronice en tiempo real con sus canales de venta online, habilitando el modelo Ship-to-Store (compra online y colocacion fisica). De este modo, la marca prepara a sus expertos y conecta de forma directa la demanda digital con el servicio tecnico de su red de mas de 100 centros de servicios y gomerias aliadas.

## Casos que marcan el rumbo en Latinoamerica

- **Volkswagen (Peru):** A traves de la plataforma de Alephee, la terminal unifico su catalogo oficial y su stock de llantas y accesorios de alta gama en Mercado Libre, permitiendo que la red de concesionarios opere bajo una misma Tienda Oficial con stock descentralizado pero integrado.
- **Renault (Argentina):** La marca digitalizo su ecosistema de repuestos originales, transformando la experiencia de compra de accesorios y neumaticos de alta gama mediante la automatizacion de procesos entre su red comercial y los principales marketplaces de la region.

*Conoce como la integracion de catalogos digitales con talleres fisicos redefine la venta de neumaticos premium en Latinoamerica*

## Regla de oro: VENDE, NO DESCRIBAS
- MALO: "La distribucion de autopartes se encamina hacia un modelo omnicanal"
- BUENO: "Un distribuidor que integro su catalogo con marketplace aumento su rotacion un 40% en 6 meses"
- MALO: "Es importante gestionar el inventario eficientemente"
- BUENO: "Cada neumatico que rota antes de los 12 meses te ahorra el 15% del costo de obsolescencia"

## Estilo
- Tono: persuasivo, especifico, con datos de impacto
- Verbos activos en PRESENTE: "optimiza", "reduce", "blinda", "garantiza", "genera"
- Beneficios medibles > caracteristicas genericas
- Menciona empresas y plataformas reales del contexto
- Tildes y ortografia impecables

## Prohibido
- Lenguaje debil: NUNCA "puede mejorar", "podria reducir". Usa "reduce", "mejora", "elimina"
- Target equivocado: NO hables de "consumidores". Tu audience: talleres, repuesteros, distribuidores
- Signos de exclamacion, "contactanos", "aprovecha", "no te lo pierdas"
- Describir el problema sin vender la solucion. SI mencionas un dolor, DESPUES mostra como se resuelve.
- OBVEDADES: NO le expliques que "los neumaticos se degradan" o que "hay que elegir la medida". El lector ya lo sabe. Habla de MARGENES y ROTACION.
- ALUCINACIONES: NUNCA inventes categorias de productos que no existen.
- DATOS INVENTADOS: NUNCA inventes estadisticas o porcentajes. Si no hay dato real en el contexto, NO uses porcentajes.
- REPETICIONES: NUNCA repitas la misma frase, especialmente en conclusiones.
- CONFUSION DE TERMINOS: neumaticos/cubiertas (goma), llantas (aleacion). Bridgestone fabrica NEUMATICOS, no ruedas. Cuando hablas de degradacion, el sujeto es el NEUMATICO, NUNCA la rueda.
- CTA DEBIL: El cierre DEBE tener urgencia y generar accion inmediata. CTA en PRESENTE con sujeto, NO en infinitivo. Sin CTA = articulo invalido.
- GENERALIZAR PLATAFORMAS: Si el contexto menciona Alephee, Mercado Libre, TecDoc, etc., MENCIONALAS por nombre. NO digas "una plataforma" o "un marketplace".
- VACIAS: NO uses listas genericas como "Mejora de la eficiencia" o "Experiencia personalizada". Cada punto debe tener un dato especifico o un ejemplo concreto.

OBLIGATORIO: El articulo DEBE terminar con meta description en *cursiva* (max 155 chars, sin etiqueta) + CTA de urgencia en PRESENTE.

{_REGLAS_UNIVERSALES}""",
    "divulgativo": f"""\
Eres un divulgador tecnico especializado en autopartes, e-commerce B2B y mecanica automotriz en Latinoamerica.

## Tu tarea
Explicar conceptos tecnicos y de negocio del sector aftermarket de forma simple y didactica.

## Contexto del sector
Tu audiencia son: repuesteros, distribuidores, gerentes de e-commerce automotor.
Ellos necesitan: entender como funcionan las plataformas, catalogacion digital, indexacion de productos.
Plataformas clave: Alephee (e-commerce B2B), Mercado Libre (marketplace), TecDoc (catalogo de referencias cruzadas), catalogacion digital.

## Estructura obligatoria (cuatro secciones ## en Markdown)
1. **Concepto con analogia** - Introduce el tema con una comparacion concreta del mundo real
2. **Como funciona** - Explicacion paso a paso del concepto o plataforma
3. **Impacto practico** - En el taller, distribuidor o repuestero
4. **Resumen + CTA** - Maximo 3 viñetas con ideas NUEVAS + llamada a la accion

## Ejemplo:
## Que es un Catalogo Digital y Por Que Importa para tu Negocio

Un catalogo digital es como una vitrina virtual donde tu stock completo esta disponible 24/7 para tus clientes. Para el distribuidor de autopartes, esto significa que cada repuesto que tenes en el deposito puede ser encontrado y vendido sin que tu equipo tenga que buscar manualmente.

## Como Funciona

La plataforma Alephee, por ejemplo, permite a los distribuidores sincronizar su catalogo con Mercado Libre, mostrando solo los productos que tienen stock disponible. Cuando un taller busca un electroventilador para VW Gol, el sistema automaticamente muestra las opciones compatibles con el motor y año del vehiculo.

## Impacto Practico

- Reduccion de devoluciones por envio de repuesto incorrecto
- Aumento de ventas por visibilidad en marketplaces
- Ahorro de tiempo en busquedas manuales de compatibilidad

*Descubre como un catalogo digital puede transformar tu negocio de repuestos*

## Estilo
- Tono: didactico, simple, analogias del mundo real
- Usa "aftermarket" directamente (NO "repuestos despues de mercado")
- Menciona plataformas reales del contexto
- Resumen: maximo 3 viñetas, cada una con idea NUEVA, sin repetir el cuerpo
- NUNCA inventes conceptos tecnicos que no existen.
- TERMINOLOGIA EXACTA: neumaticos/cubiertas (goma), llantas (aleacion). NUNCA mezcles.
- Sin repeticiones en conclusiones.

OBLIGATORIO: El articulo DEBE terminar con meta description en *cursiva* (max 155 chars, sin etiqueta) + CTA. Sin meta description = articulo invalido.

{_REGLAS_UNIVERSALES}""",
    "ejecutivo": f"""\
Eres un analista de negocio y estrategia especializado en la industria de autopartes y e-commerce B2B en Latinoamerica.

## Tu tarea
Generar un articulo ejecutivo con perspectiva de alto nivel sobre el sector aftermarket y digitalizacion.

## Contexto del sector
Tu audiencia son: gerentes de distribuidores, directores de e-commerce, dueños de redes de talleres.
Ellos necesitan: estrategia digital, ROI, eficiencia operativa, integracion con marketplaces.
Plataformas clave: Alephee (e-commerce B2B), Mercado Libre (marketplace), TecDoc (catalogo de referencias cruzadas), tiendas oficiales multivendedor.

## Estructura obligatoria (cuatro secciones ## en Markdown)
1. **Panorama macro** - Numeros gruesos del sector e-commerce automotor
2. **Desafio estrategico** - Margenes, costos logisticos, integracion digital
3. **Hoja de ruta** - Digitalizacion de la cadena de valor con plataformas reales
4. **Recomendaciones + CTA** - ROI, eficiencia, mitigacion de riesgos + llamada a la accion

## Ejemplo:
## El Futuro del E-commerce en Autopartes: Estrategias para Distribuidores

El mercado de autopartes online en Latinoamerica esta creciendo a un ritmo del **25% anual**, pero muchos distribuidores aun operan sin estrategia digital definida. La presion sobre los margenes exige una revision estrategica de la cadena de suministro.

## Desafio Estrategico

Los distribuidores que no integran sus catalogos con marketplaces como Mercado Libre estan perdiendo hasta el **30% de ventas potenciales**. La solucion no es solo tecnologia: es transformar el modelo de negocio.

## Hoja de Ruta

Plataformas como Alephee permiten a los distribuidores crear tiendas oficiales multivendedor, integrando stock fisico con ventas digitales. Esto reduce devoluciones un **40%** y aumenta la rotacion de inventario.

## Recomendaciones

- Evaluar ROI de integracion con marketplace antes de 6 meses
- Priorizar catalogacion digital de productos de alta rotacion
- Medir devoluciones por fitment incorrecto como KPI principal

*Descubre como transformar tu estrategia digital en el sector autopartista*

## Estilo
- Tono: directivo, conciso, basado en datos
- Perspectiva de alto nivel
- Menciona empresas y plataformas reales del contexto

## Prohibido
- Inventar palabras ("presionamiento")
- Repetir frases mas de una vez
- Lenguaje corporativo vacio. Usa: ROI, costos, margenes, riesgos logisticos
- NUNCA inventes conceptos tecnicos que no existen.
- NO expliques obviedades al lector B2B.
- TERMINOLOGIA EXACTA: neumaticos/cubiertas (goma), llantas (aleacion). NUNCA mezcles.
- GENERALIZAR PLATAFORMAS: Si el contexto menciona Alephee, Mercado Libre, TecDoc, etc., MENCIONALAS por nombre.

OBLIGATORIO: El articulo DEBE terminar con meta description en *cursiva* (max 155 chars, sin etiqueta) + CTA. Sin meta description = articulo invalido.

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
Analizar el articulo y validar el cumplimiento de lineamientos de estilo y formato.

## Lineamientos a evaluar
1. **estructura_correcta** - Contiene secciones (##) bien definidas con titulos coherentes?
2. **formato_negritas** - Cifras, porcentajes, empresas y fechas en **negrita**?
3. **vocabulario_negocio** - Usa terminos del sector ("parque automotor", "demanda cautiva", "cadena de valor")?
4. **tono_b2b** - Lenguaje directo, profesional, enfocado al negocio?
5. **sin_paywall** - Sin frases de suscripcion o paywalls?
6. **no_repetitivo** - Cada seccion aporta informacion nueva?
7. **sin_alucinaciones** - No inventa conceptos tecnicos que no existen?
8. **sin_obviedades** - No explica cosas basicas que el lector B2B ya sabe?
9. **terminologia_correcta** - Usa los terminos correctos (neumaticos vs llantas, pastillas vs balatas)?

## Formato de salida
Responde UNICAMENTE con este JSON:
{
  "lineamientos": {
    "estructura_correcta": boolean,
    "formato_negritas": boolean,
    "vocabulario_negocio": boolean,
    "tono_b2b": boolean,
    "sin_paywall": boolean,
    "no_repetitivo": boolean,
    "sin_alucinaciones": boolean,
    "sin_obviedades": boolean,
    "terminologia_correcta": boolean
  },
  "comentarios": "string (breve observacion general)"
}"""

_DISPONIBLE = True


# ── Helpers internos ───────────────────────────────────────────────────────────


def _get_base_url() -> str:
    """URL base según el proveedor activo."""
    if AI_PROVIDER == "nvidia" and NVIDIA_API_KEY:
        return NVIDIA_BASE_URL
    return LMSTUDIO_URL


def _get_model() -> str:
    """Nombre del modelo según el proveedor activo."""
    if AI_PROVIDER == "nvidia" and NVIDIA_API_KEY:
        return NVIDIA_MODEL
    return MODELO


def _get_emb_model() -> str:
    """Nombre del modelo de embeddings según el proveedor activo."""
    if AI_PROVIDER == "nvidia" and NVIDIA_API_KEY:
        return NVIDIA_EMB_MODEL
    return MODELO_EMB


def _get_headers() -> dict:
    """Headers HTTP según el proveedor activo."""
    if AI_PROVIDER == "nvidia" and NVIDIA_API_KEY:
        return {"Authorization": f"Bearer {NVIDIA_API_KEY}"}
    return {}


def _post(endpoint: str, payload: dict, timeout: int = 60, stream: bool = False, retries: int = 3) -> requests.Response:
    """POST unificado con URL, headers, timeout y retry con backoff para 429.
    Si el modelo principal (GLM) get 429, intenta con el fallback (Llama)."""
    url = f"{_get_base_url()}{endpoint}"
    modelo_original = payload.get("model", "")
    for intento in range(retries):
        resp = requests.post(url, json=payload, headers=_get_headers(), timeout=timeout, stream=stream)
        if resp.status_code != 429:
            return resp
        # Si es el primer intento y tenemos modelo fallback, probarlo
        if intento == 0 and modelo_original == NVIDIA_MODEL and NVIDIA_FALLBACK_MODEL and endpoint == "/chat/completions":
            payload_fallback = {**payload, "model": NVIDIA_FALLBACK_MODEL}
            resp_fb = requests.post(url, json=payload_fallback, headers=_get_headers(), timeout=timeout, stream=stream)
            if resp_fb.status_code == 200:
                if not stream:
                    print(f"[FALLBACK] GLM-5.2 rate-limited -> usando {NVIDIA_FALLBACK_MODEL}", flush=True)
                return resp_fb
        wait = min(5 * (2 ** intento), 60)
        if not stream:
            print(f"[RETRY] 429 en {endpoint} - esperando {wait}s (intento {intento+1}/{retries})", flush=True)
        time.sleep(wait)
    return resp


def _call_lm(
    mensaje_usuario: str, temperature: float = 0.1, max_tokens: int = 2048, system_prompt: str | None = None
) -> str:
    """Envía un mensaje sin streaming y devuelve el texto completo."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": mensaje_usuario})
    payload = {
        "model": _get_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    resp = _post("/chat/completions", payload, retries=5)
    if resp.status_code == 429:
        raise RuntimeError("Rate limit de NVIDIA (429). Esperá unos minutos y reintentá.")
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
    """Verifica que el proveedor activo responda. Devuelve True si está disponible."""
    global _DISPONIBLE
    try:
        url = f"{_get_base_url()}/models"
        requests.get(url, headers=_get_headers(), timeout=5)
        _DISPONIBLE = True
    except Exception:
        _DISPONIBLE = False
        proveedor = "NVIDIA" if AI_PROVIDER == "nvidia" else "LM Studio"
        print(f"[AVISO] {proveedor} ({_get_base_url()}) no disponible. Los artículos se guardarán sin filtrar.")
    return _DISPONIBLE


def _check_local() -> bool:
    """Verifica si LM Studio local está disponible."""
    try:
        requests.get(f"{LMSTUDIO_URL}/models", timeout=5)
        return True
    except Exception:
        return False


def verificar_provider() -> dict:
    """Estado actual del proveedor y disponibilidad."""
    return {
        "provider": AI_PROVIDER,
        "local_available": _check_local(),
        "nvidia_available": bool(NVIDIA_API_KEY),
        "model": _get_model(),
        "emb_model": _get_emb_model(),
    }


def set_provider(provider: str) -> dict:
    """
    Cambia el proveedor de IA en tiempo de ejecución.

    Args:
        provider: "local" o "nvidia"

    Returns:
        {"success": bool, "provider": str, ...} o {"success": False, "error": str}
    """
    global AI_PROVIDER
    if provider not in ("local", "nvidia"):
        return {"success": False, "error": "Proveedor inválido. Usá 'local' o 'nvidia'."}
    if provider == "nvidia" and not NVIDIA_API_KEY:
        return {"success": False, "error": "No hay API key de NVIDIA configurada."}
    AI_PROVIDER = provider
    os.environ["AI_PROVIDER"] = provider
    verificar_conexion()
    return {"success": True, "provider": AI_PROVIDER, **verificar_provider()}


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
        "model": _get_model(),
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
            resp = _post("/chat/completions", payload)
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
    choices = chunk.get("choices", [])
    if choices:
        delta = choices[0].get("delta", {})
        # Contenido principal
        content = delta.get("content", "")
        if content:
            return content
        # Razonamiento (NVIDIA GLM-5.2 envia reasoning aqui)
        reasoning = delta.get("reasoning_content", "")
        if reasoning:
            return reasoning
    # Formato nativo llama.cpp: {"content":"...","stop":false}
    return chunk.get("content", "")


def _post_procesar_articulo(texto: str) -> str:
    """Post-procesamiento: detecta y elimina repeticiones, limpia artefactos comunes de modelos debiles."""
    if not texto or len(texto) < 100:
        return texto

    lineas = texto.split("\n")

    # 1. Eliminar conclusiones duplicadas (misma frase pegada 2+ veces al final)
    if len(lineas) >= 3:
        ultima_no_vacia = ""
        for ln in reversed(lineas):
            stripped = ln.strip()
            if stripped and not stripped.startswith("*"):
                ultima_no_vacia = stripped
                break
        if ultima_no_vacia:
            conteo = sum(1 for ln in lineas if ln.strip() == ultima_no_vacia)
            if conteo >= 2:
                # Mantener solo la primera ocurrencia
                nueva_lineas = []
                primera_encontrada = False
                for ln in lineas:
                    if ln.strip() == ultima_no_vacia and not primera_encontrada:
                        nueva_lineas.append(ln)
                        primera_encontrada = True
                    elif ln.strip() != ultima_no_vacia:
                        nueva_lineas.append(ln)
                lineas = nueva_lineas

    # 2. Eliminar oraciones repetidas dentro de un mismo parrafo
    resultado_final = []
    for ln in lineas:
        stripped = ln.strip()
        # Si la linea es muy larga, buscar oraciones duplicadas
        if len(stripped) > 80 and stripped.count(".") >= 2:
            oraciones = [o.strip() for o in stripped.split(".") if o.strip()]
            vistas = set()
            oraciones_unicas = []
            for o in oraciones:
                normalizada = re.sub(r'\s+', ' ', o.lower())
                if normalizada not in vistas:
                    vistas.add(normalizada)
                    oraciones_unicas.append(o)
            if len(oraciones_unicas) < len(oraciones):
                resultado_final.append(". ".join(oraciones_unicas) + ".")
                continue
        resultado_final.append(ln)

    return "\n".join(resultado_final)


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
        contexto = f"TEMA: {tema}\n\n{contexto}"

    if research:
        mensaje = f"Redacta un articulo B2B estilo blog sobre el siguiente contexto. Usa la estructura y reglas de tu system prompt.\n\nCONTEXTO:\n{contexto}\n\nRESEARCH:\n{research}"
    else:
        mensaje = f"Redacta un articulo B2B estilo blog sobre el siguiente contexto. Usa la estructura y reglas de tu system prompt.\n\nCONTEXTO:\n{contexto}"

    payload = {
        "model": _get_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": mensaje},
        ],
        "temperature": 0.7,
        "max_tokens": 4000,
        "stream": True,
    }

    # Heartbeat para mostrar que sigue vivo mientras espera el primer token
    try:
        response = _post("/chat/completions", payload, timeout=1800, stream=True, retries=5)
    except Exception:
        raise

    if not response.ok:
        error_body = response.text[:2000]
        if response.status_code == 429:
            raise RuntimeError(f"Rate limit de NVIDIA (429). Esperá unos minutos y reintentá. Detalle: {error_body}")
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

    result = _post_procesar_articulo(result)

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
        "model": _get_model(),
        "messages": [
            {"role": "system", "content": PROMPT_TEMAS},
            {"role": "user", "content": texto},
        ],
        "temperature": 0.3,
        "max_tokens": 512,
        "stream": False,
    }

    try:
        resp = _post("/chat/completions", payload, retries=5)
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
        "model": _get_model(),
        "messages": [
            {"role": "system", "content": PROMPT_RESEARCH},
            {"role": "user", "content": contexto},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
        "stream": False,
    }

    try:
        resp = _post("/chat/completions", payload, retries=5)
        resp.raise_for_status()
        texto = resp.json()["choices"][0]["message"]["content"].strip()
        data = _extraer_json(texto)
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return '{"empresas":[],"ejecutivos":[],"datos":[],"tendencias":[],"tema_principal":""}'


# ── Embeddings ─────────────────────────────────────────────────────────────────


def calcular_embedding(texto: str, input_type: str = "passage") -> list[float] | None:
    """
    Devuelve el vector de embedding (significado) del texto, o None si falla.

    El vector se calcula UNA vez por articulo y se guarda en la BD; agrupar y
    comparar despues es pura matematica (similitud coseno), sin volver a llamar
    al modelo. El modelo nomic admite ~8k tokens, truncamos por seguridad.

    Args:
        texto: texto a vectorizar
        input_type: "passage" (contenido) o "query" (busqueda). Solo aplica para NVIDIA.
    """
    texto = (texto or "").strip()
    if not texto:
        return None
    max_chars = 1500 if AI_PROVIDER == "nvidia" else 8000
    payload = {"model": _get_emb_model(), "input": texto[:max_chars]}
    if AI_PROVIDER == "nvidia":
        payload["input_type"] = input_type

    # Retry manual: NVIDIA a veces devuelve 400 en vez de 429 para rate limit en embeddings
    # Nota: NO usamos retries internos en _post() para evitar double-retry stack
    for intento in range(5):
        try:
            resp = _post("/embeddings", payload, timeout=30, retries=1)
            if resp.status_code in (400, 429):
                wait = [0.5, 1, 2, 3, 3][intento]
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except Exception:
            if intento < 4:
                time.sleep([0.5, 1, 2, 3, 3][intento])
                continue
            print(f"[AVISO] No se pudo calcular embedding tras 5 intentos.")
            return None
    return None


# ── Verificar conectividad al importar ────────────────────────────────────────

verificar_conexion()


# ── Test rápido (python lm_studio.py) ─────────────────────────────────────────

if __name__ == "__main__":
    print(f"🔌 Proveedor: {AI_PROVIDER} | Modelo: {_get_model()}")
    print(f"   URL: {_get_base_url()}")
    try:
        r = clasificar_articulo(
            "Nueva línea de frenos para camiones",
            "La empresa XYZ lanzó una nueva línea de pastillas de freno para camiones pesados.",
        )
        print(f"Resultado: {json.dumps(r, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        print("Verificá la configuración del proveedor en .env")
