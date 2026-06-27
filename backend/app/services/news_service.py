import json
import re
import time
from functools import wraps
from typing import List, Optional
from groq import Groq
from app.config import GROQ_API_KEY
from app.data.parser import fetch_news_headlines as _fetch_headlines

client = Groq(api_key=GROQ_API_KEY)

# ============================================================================
# DECORADOR DE REINTENTOS PARA RATE LIMITS
# ============================================================================

def retry_on_rate_limit(max_retries=3, base_delay=1):
    """Decorador para reintentar en caso de rate limit de Groq."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_msg = str(e).lower()
                    if "rate_limit" in error_msg or "429" in error_msg:
                        delay = base_delay * (2 ** attempt)
                        print(f"⏳ Rate limit alcanzado. Reintentando en {delay:.2f}s (intento {attempt+1}/{max_retries})")
                        time.sleep(delay)
                        last_error = e
                        continue
                    else:
                        # Otro tipo de error, lo propagamos
                        raise
            # Si llegamos aquí, todos los reintentos fallaron
            print(f"❌ Fallaron todos los reintentos para {func.__name__}: {last_error}")
            return None
        return wrapper
    return decorator

# ============================================================================
# PROMPTS
# ============================================================================

SENTIMENT_PROMPT = """Analiza los titulares de noticias sobre {team_name} en el Mundial 2026.

Tu tarea: determinar si las noticias indican un factor positivo o negativo para el rendimiento del equipo.

FACTORES NEGATIVOS (bajan score):
- Lesiones confirmadas de jugadores clave (titular, capitan, goleador).
- Malos resultados recientes (derrotas, goleadas en contra).
- Conflictos internos, cambio de entrenador, sanciones FIFA.
- Baja moral o declaraciones pesimistas de jugadores/DT.

FACTORES POSITIVOS (suben score):
- Buena preparacion, victorias en amistosos previos.
- Regreso de estrellas lesionadas, alta moral del grupo.
- Declaraciones de confianza del cuerpo tecnico.

INSTRUCCIONES ESTRICTAS:
- Responde SOLO con un JSON valido, sin texto adicional.
- sentiment_score: numero entre -1.0 y 1.0.
- reason: MAXIMO 50 caracteres. Se ultra conciso. Ejemplo: "Lesion del delantero titular" o "Buena racha previa".
- NO uses comillas dobles dentro del campo reason. Usa comillas simples si necesitas.

Ejemplo de respuesta correcta:
{{"sentiment_score": -0.6, "reason": "Lesion confirmada del capitan"}}

Titulares:
{headlines}
"""

SUMMARY_PROMPT = """Resume en 1 o 2 frases cortas (maximo 100 caracteres) los titulares sobre {team_name} en el Mundial 2026.
Responde SOLO con el resumen, sin JSON, sin comillas, sin formato especial.

Titulares:
{headlines}
"""

MATCH_SUMMARY_PROMPT = """Resume en una oración corta (máximo 100 caracteres) lo más destacado del partido entre {home} y {away} en el Mundial 2026.
Si no hay información específica, di que no hay noticias.
Resumen:"""

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def _clean_json(text: str) -> str:
    """Extrae JSON de respuestas con markdown o texto extra."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end+1]
    return text.strip()

def fallback_sentiment(headlines: list) -> tuple:
    """Diccionario de polaridad simple en espanol."""
    positivo = [
        "gana", "clasifica", "recupera", "favorito", "imparable", "triunfo",
        "historico", "golea", "victoria", "gano", "vencio", "campeon", "lider"
    ]
    negativo = [
        "lesion", "grave", "baja", "derrota", "eliminado", "polemica",
        "criticas", "sancionado", "duda", "perdio", "goleada", "crisis",
        "renuncia", "despedido", "suspendido"
    ]
    score = 0.0
    for h in headlines:
        h_lower = h.lower()
        score += sum(0.1 for word in positivo if word in h_lower)
        score -= sum(0.15 for word in negativo if word in h_lower)
    score = max(-0.8, min(0.8, score))

    if score > 0.3:
        reason = "Noticias con tono positivo"
    elif score < -0.3:
        reason = "Noticias con tono negativo"
    else:
        reason = "Noticias neutrales"
    return score, reason

# ============================================================================
# FUNCIONES PRINCIPALES CON REINTENTOS
# ============================================================================

@retry_on_rate_limit(max_retries=3, base_delay=1)
def analyze_sentiment(team_name: str, headlines: list) -> tuple:
    """Devuelve (score, reason). Si falla, usa fallback."""
    if not headlines or all("no se encontraron" in h.lower() for h in headlines):
        return 0.0, "Sin noticias relevantes"

    headlines_text = "\n".join(f"- {h}" for h in headlines[:5])
    prompt = SENTIMENT_PROMPT.format(team_name=team_name, headlines=headlines_text)
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.05,
            max_tokens=80,
            response_format={"type": "json_object"},
        )
        response_text = _clean_json(chat_completion.choices[0].message.content)
        result = json.loads(response_text)
        score = float(result["sentiment_score"])
        score = max(-1.0, min(1.0, score))
        reason = result.get("reason", "Analisis completado")
        reason = reason[:50]
        return score, reason
    except Exception as e:
        print(f"Error en Groq sentiment: {e}")
        return fallback_sentiment(headlines)

@retry_on_rate_limit(max_retries=3, base_delay=1)
def summarize_headlines(team: str, headlines: List[str]) -> str:
    """Genera un resumen corto de las noticias de un equipo."""
    if not headlines or headlines == [f"No se encontraron noticias sobre {team}"]:
        return f"Sin noticias relevantes sobre {team}"

    headlines_text = "\n".join(f"- {h}" for h in headlines[:5])
    prompt = SUMMARY_PROMPT.format(team_name=team, headlines=headlines_text)
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.3,
            max_tokens=80,
        )
        summary = chat_completion.choices[0].message.content.strip()
        if len(summary) > 120:
            summary = summary[:117] + "..."
        return summary
    except Exception as e:
        print(f"Error generando resumen para {team}: {e}")
        return " ".join(headlines[:2])[:100] + "..."

@retry_on_rate_limit(max_retries=3, base_delay=1)
def fetch_match_news_summary(home: str, away: str) -> str:
    """Genera un resumen corto del partido entre home y away."""
    prompt = MATCH_SUMMARY_PROMPT.format(home=home, away=away)
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.3,
            max_tokens=80,
        )
        summary = chat_completion.choices[0].message.content.strip()
        if len(summary) > 120:
            summary = summary[:117] + "..."
        return summary
    except Exception as e:
        print(f"Error generando resumen del partido: {e}")
        return f"Partido entre {home} y {away} en el Mundial 2026."

# ============================================================================
# ANÁLISIS PROFUNDO CON MEJOR MODELO (bajo demanda)
# ============================================================================

DEEP_ANALYSIS_PROMPT = """Eres un analista deportivo de élite del Mundial 2026.

Partido: {home} vs {away}
Grupo: {group} | Fecha: {date} | Sede: {venue}

Noticias {home}:
{home_headlines}

Noticias {away}:
{away_headlines}

Genera un análisis JSON con esta estructura EXACTA:
{{
    "home_summary": "Resumen de 1-2 frases sobre {home} (máx 130 chars)",
    "away_summary": "Resumen de 1-2 frases sobre {away} (máx 130 chars)",
    "match_preview": "Pronóstico breve del partido en 1-2 frases (máx 150 chars)",
    "key_factors": ["Factor clave 1", "Factor clave 2", "Factor clave 3"],
    "home_form": "Alta/Media/Baja",
    "away_form": "Alta/Media/Baja",
    "predicted_winner": "home/away/empate",
    "confidence": "Alta/Media/Baja"
}}

Reglas estrictas:
- Responde SOLO con el JSON, sin texto antes o después
- Sin markdown, sin backticks
- Usa comillas simples dentro de los textos si necesitas, NUNCA dobles
- Máximo 3 key_factors, cada uno máximo 50 caracteres
- home_form/away_form: basado en noticias recientes
- predicted_winner: quien tiene más ventaja según las noticias
- confidence: qué tan claro es el pronóstico
"""

def generate_match_analysis(home: str, away: str, home_headlines: list,
                             away_headlines: list, match_data: dict = None) -> dict:
    """Análisis profundo con llama-3.3-70b-versatile (mejor modelo Groq)."""
    venue = match_data.get("venue", "Por determinar") if match_data else "Por determinar"
    group = match_data.get("group", "") if match_data else ""
    date = match_data.get("date", "") if match_data else ""

    home_hl = "\n".join(f"- {h}" for h in home_headlines[:5]) if home_headlines else "Sin noticias"
    away_hl = "\n".join(f"- {h}" for h in away_headlines[:5]) if away_headlines else "Sin noticias"

    prompt = DEEP_ANALYSIS_PROMPT.format(
        home=home, away=away, group=group, date=date, venue=venue,
        home_headlines=home_hl, away_headlines=away_hl
    )

    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.4,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        result = json.loads(_clean_json(chat_completion.choices[0].message.content))

        # Validar y truncar campos
        for field, max_len in [("home_summary", 130), ("away_summary", 130), ("match_preview", 150)]:
            val = result.get(field, "")
            if not val:
                result[field] = ""
            elif len(val) > max_len:
                result[field] = val[:max_len - 3] + "..."

        factors = result.get("key_factors", [])
        result["key_factors"] = [f[:50] for f in factors[:3]]

        for field in ["home_form", "away_form", "predicted_winner", "confidence"]:
            if field not in result:
                result[field] = "Media"

        return result

    except Exception as e:
        print(f"Error análisis profundo {home} vs {away}: {e}")
        hs = " ".join(home_headlines[:2])[:127] + "..." if home_headlines else "Sin noticias"
        as_ = " ".join(away_headlines[:2])[:127] + "..." if away_headlines else "Sin noticias"
        return {
            "home_summary": hs,
            "away_summary": as_,
            "match_preview": f"Partido entre {home} y {away} en el Mundial 2026.",
            "key_factors": [],
            "home_form": "Media",
            "away_form": "Media",
            "predicted_winner": "empate",
            "confidence": "Baja"
        }
