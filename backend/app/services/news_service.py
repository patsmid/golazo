import json
import re
from groq import Groq
from app.config import GROQ_API_KEY
from app.data.parser import fetch_news_headlines as _fetch_headlines

client = Groq(api_key=GROQ_API_KEY)


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


def summarize_headlines(team_name: str, headlines: list) -> str:
    """Genera un resumen corto de 1-2 frases de los titulares. Fallback a concatenacion."""
    if not headlines or all("no se encontraron" in h.lower() for h in headlines):
        return "Sin noticias recientes."

    headlines_text = "\n".join(f"- {h}" for h in headlines[:5])
    prompt = SUMMARY_PROMPT.format(team_name=team_name, headlines=headlines_text)
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            max_tokens=60,
        )
        summary = chat_completion.choices[0].message.content.strip()
        summary = summary.replace('"', "").replace("'", "").replace("```", "")
        return summary[:120]
    except Exception as e:
        print(f"Error en Groq summary: {e}")
        return " | ".join(headlines[:2])[:120]


def fetch_match_news_summary(home: str, away: str) -> str:
    """Busca y resume noticias sobre el partido especifico."""
    query = f"{home} vs {away} mundial 2026"
    headlines = _fetch_headlines(query)
    return summarize_headlines(f"{home} vs {away}", headlines)


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
