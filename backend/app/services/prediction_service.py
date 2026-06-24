import asyncio
import time
import math
from typing import Dict, Optional, List
from app.models.elo import EloManager
from app.models.dixon_coles import elo_to_lambda, dixon_coles_probabilities
from app.data.fetcher import fetch_upcoming_matches, fetch_all_matches
from app.cache.redis_client import cache_get, cache_set, redis_client
from app.services.news_service import analyze_sentiment
from app.services.odds_service import get_enriched_odds
from app.data.parser import fetch_news_headlines
from app.config import GROQ_API_KEY

# Groq es opcional
try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except ImportError:
    groq_client = None

elo_manager = EloManager()

HOST_COUNTRIES = {"mexico", "united states", "canada"}
SENTIMENT_BETA = 0.03
MODEL_VERSION = "1.0.1"
PROCESSED_MATCHES_KEY = "processed_wc_matches"


# ============================================================================
# HELPERS
# ============================================================================

def is_host_team(team: str, country: Optional[str]) -> bool:
    if not country:
        return False
    return any(host in country.lower() for host in HOST_COUNTRIES)


def safe_lambda(value: float) -> float:
    return max(0.2, min(4.5, value))


def calculate_confidence(probs: Dict[str, float]) -> str:
    sorted_probs = sorted(probs.values(), reverse=True)
    diff = sorted_probs[0] - sorted_probs[1]
    if diff > 0.25:
        return "Alta"
    elif diff > 0.12:
        return "Media"
    return "Baja"


def format_recent_matches(team_name: str, matches: List[Dict]) -> str:
    """Formatea una lista de partidos (ya filtrados por equipo) en un texto legible."""
    if not matches:
        return "Sin partidos recientes."
    lines = []
    for m in matches[:5]:  # máximo 5
        date = m.get("date", "")
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        home_goals = m.get("home_score")
        away_goals = m.get("away_score")
        if home_goals is None or away_goals is None:
            continue
        # Determinar si el equipo es local o visitante
        if home == team_name:
            result = f"{home_goals}-{away_goals} vs {away}"
        else:
            result = f"{away_goals}-{home_goals} vs {home}"
        lines.append(f"{date}: {result}")
    return "\n".join(lines)

def summarize_recent_matches(matches: List[Dict], team: str) -> List[Dict]:
    """
    Convierte lista de partidos completos a un resumen con fecha, rival y marcador.
    """
    summary = []
    for m in matches[:5]:
        if m["home_team"] == team:
            opponent = m["away_team"]
            gf = m["home_score"]
            ga = m["away_score"]
        else:
            opponent = m["home_team"]
            gf = m["away_score"]
            ga = m["home_score"]
        summary.append({
            "date": m.get("date"),
            "opponent": opponent,
            "goals_for": gf,
            "goals_against": ga,
            "result": f"{gf}-{ga}"
        })
    return summary


# ============================================================================
# PREDICCIÓN BASE (SIN NOTICIAS)
# ============================================================================

def base_prediction(match: dict) -> dict:
    home = match["home_team"]
    away = match["away_team"]
    country = match.get("country", "")

    elo_home = elo_manager.get_rating(home)
    elo_away = elo_manager.get_rating(away)

    is_host = is_host_team(home, country)
    lambda_home, lambda_away = elo_to_lambda(elo_home, elo_away, is_host)

    lambda_home = safe_lambda(lambda_home)
    lambda_away = safe_lambda(lambda_away)

    probs, top_scores = dixon_coles_probabilities(lambda_home, lambda_away)

    return {
        "elo_home": elo_home,
        "elo_away": elo_away,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "probs": probs,
        "top_scores": top_scores,
        "stage": match.get("stage", ""),
        "is_host_match": is_host
    }


# ============================================================================
# SENTIMIENTO (NOTICIAS)
# ============================================================================

async def apply_sentiment(home: str, away: str, lambda_home: float, lambda_away: float):
    try:
        headlines_home, headlines_away = await asyncio.gather(
            asyncio.to_thread(fetch_news_headlines, home),
            asyncio.to_thread(fetch_news_headlines, away)
        )

        score_home, reason_home = analyze_sentiment(home, headlines_home)
        score_away, reason_away = analyze_sentiment(away, headlines_away)

        lambda_home *= math.exp(SENTIMENT_BETA * score_home)
        lambda_away *= math.exp(SENTIMENT_BETA * score_away)

        return lambda_home, lambda_away, {
            "home_score": score_home,
            "away_score": score_away,
            "home_reason": reason_home,
            "away_reason": reason_away
        }
    except Exception:
        return lambda_home, lambda_away, {
            "home_score": 0,
            "away_score": 0,
            "home_reason": "No data",
            "away_reason": "No data"
        }


# ============================================================================
# CONVERSIÓN DE ODDS A PROBABILIDAD
# ============================================================================

def convert_decimal_to_probability(decimal_odds: float) -> float:
    if decimal_odds and decimal_odds > 0:
        return 1.0 / decimal_odds
    return 0.0


# ============================================================================
# ANÁLISIS CON GROQ
# ============================================================================

GROQ_ANALYSIS_PROMPT = """Eres un experto analista de fútbol y pronosticador deportivo.

Analiza el siguiente partido del Mundial 2026 y genera un pronóstico completo y fundamentado.

## Partido
{home_team} vs {away_team}
Fecha: {date}
Etapa: {stage}

## Pronóstico del Modelo Estadístico (Dixon-Coles + Elo)
- Ganador: {model_winner} ({model_winner_code})
- Marcador más probable: {model_score}
- Probabilidades: Local {model_home_win:.1%} | Empate {model_draw:.1%} | Visitante {model_away_win:.1%}
- Goles Esperados (xG): Local {model_xg_home:.2f} | Visitante {model_xg_away:.2f}
- Confianza: {model_confidence}

## Odds de Casas de Apuestas (Consenso de {odds_count} casas)
- Local: {odds_home:.2f} (prob. implícita {odds_home_prob:.1%})
- Empate: {odds_draw:.2f} (prob. implícita {odds_draw_prob:.1%})
- Visitante: {odds_away:.2f} (prob. implícita {odds_away_prob:.1%})
- Pronóstico por odds: {odds_winner} (marcador estimado: {odds_score})

## Top 3 Casas de Apuestas
{top_bookmakers_text}

## Historial reciente (últimos 5 partidos)
- {home_team}:
{recent_home_text}
- {away_team}:
{recent_away_text}

## Noticias y Sentimiento
- {home_team}: {sentiment_home_reason} (score: {sentiment_home_score:.1f})
- {away_team}: {sentiment_away_reason} (score: {sentiment_away_score:.1f})

## Instrucciones
Genera un análisis CONCISO pero COMPLETO (máximo 250 palabras) que:

1. Compare el pronóstico del modelo con el consenso de las casas de apuestas.
2. Identifique si hay discrepancias significativas y qué podría explicarlas (lesiones, motivación, etc.).
3. Destaque el factor más relevante que podría inclinar el partido.
4. Dé una recomendación final clara: quién es favorito y por qué.

Formato de respuesta: Texto plano, párrafos cortos, sin markdown ni listas.

ANÁLISIS:"""


async def generate_groq_analysis(
    home_team: str,
    away_team: str,
    date: str,
    stage: str,
    model_probs: Dict,
    model_score: str,
    model_winner: str,
    model_winner_code: str,
    model_confidence: str,
    model_xg_home: float,
    model_xg_away: float,
    odds_data: Dict,
    sentiment_data: Dict,
    recent_home_text: str = "No disponible",
    recent_away_text: str = "No disponible"
) -> str:
    """
    Genera análisis usando Groq. Si no hay API key o falla, devuelve un mensaje.
    """
    if not groq_client:
        return "No se pudo generar el análisis (falta clave de API de Groq)."

    try:
        consensus = odds_data.get("consensus", {})
        odds_count = consensus.get("num_bookmakers", 0)
        odds_home = consensus.get("home_odds", 0)
        odds_away = consensus.get("away_odds", 0)
        odds_draw = consensus.get("draw_odds", 0)

        odds_pred = odds_data.get("prediction", {})
        odds_winner = odds_pred.get("winner", "N/A")
        odds_score = odds_data.get("score_prediction", {}).get("score", "N/A")

        odds_home_prob = convert_decimal_to_probability(odds_home)
        odds_draw_prob = convert_decimal_to_probability(odds_draw)
        odds_away_prob = convert_decimal_to_probability(odds_away)

        top_bks = odds_data.get("top_bookmakers", [])
        top_text = ""
        for bk in top_bks:
            top_text += f"- {bk.get('name')}: {bk.get('home_odds', 'N/A')} / {bk.get('draw_odds', 'N/A')} / {bk.get('away_odds', 'N/A')}\n"
        if not top_text:
            top_text = "No disponible"

        sent_home = sentiment_data.get("home_reason", "Sin datos") if sentiment_data else "Sin datos"
        sent_away = sentiment_data.get("away_reason", "Sin datos") if sentiment_data else "Sin datos"
        sent_home_score = sentiment_data.get("home_score", 0) if sentiment_data else 0
        sent_away_score = sentiment_data.get("away_score", 0) if sentiment_data else 0

        winner_map = {"home": "Local", "away": "Visitante", "draw": "Empate"}
        model_winner_text = winner_map.get(model_winner_code, model_winner)

        prompt = GROQ_ANALYSIS_PROMPT.format(
            home_team=home_team,
            away_team=away_team,
            date=date or "Fecha por confirmar",
            stage=stage or "Fase de grupos",
            model_winner=model_winner,
            model_winner_code=model_winner_text,
            model_score=model_score,
            model_home_win=model_probs.get("home_win", 0),
            model_draw=model_probs.get("draw", 0),
            model_away_win=model_probs.get("away_win", 0),
            model_xg_home=model_xg_home,
            model_xg_away=model_xg_away,
            model_confidence=model_confidence,
            odds_count=odds_count,
            odds_home=odds_home if odds_home else 0,
            odds_draw=odds_draw if odds_draw else 0,
            odds_away=odds_away if odds_away else 0,
            odds_home_prob=odds_home_prob,
            odds_draw_prob=odds_draw_prob,
            odds_away_prob=odds_away_prob,
            odds_winner=odds_winner,
            odds_score=odds_score,
            top_bookmakers_text=top_text,
            sentiment_home_reason=sent_home,
            sentiment_away_reason=sent_away,
            sentiment_home_score=sent_home_score,
            sentiment_away_score=sent_away_score,   # <--- CORREGIDO: coma añadida
            recent_home_text=recent_home_text,
            recent_away_text=recent_away_text
        )

        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.3,
            max_tokens=500,
        )
        analysis = chat_completion.choices[0].message.content.strip()
        return analysis

    except Exception as e:
        print(f"❌ Error generando análisis Groq: {e}")
        return "No se pudo generar el análisis automático."


# ============================================================================
# PREDICCIÓN COMPLETA
# ============================================================================

async def generate_prediction(match: dict, use_sentiment: bool = True, use_odds: bool = True,
                              recent_home: List[Dict] = None, recent_away: List[Dict] = None):
    home = match["home_team"]
    away = match["away_team"]

    base = base_prediction(match)
    lambda_home = base["lambda_home"]
    lambda_away = base["lambda_away"]

    if recent_home is not None and recent_away is not None and len(recent_home) > 0 and len(recent_away) > 0:
        # Calcular promedio de goles marcados por cada equipo en sus últimos partidos
        home_goals_scored = []
        for m in recent_home:
            if m["home_team"] == home:
                home_goals_scored.append(m["home_score"])
            else:  # jugó de visitante
                home_goals_scored.append(m["away_score"])
        away_goals_scored = []
        for m in recent_away:
            if m["home_team"] == away:
                away_goals_scored.append(m["home_score"])
            else:
                away_goals_scored.append(m["away_score"])

        # Media global de goles por equipo en el Mundial (valor estimado)
        MEDIA_GLOBAL = 1.2

        if home_goals_scored:
            avg_home = sum(home_goals_scored) / len(home_goals_scored)
            factor_home = avg_home / MEDIA_GLOBAL
            # Limitar el factor para no disparar demasiado (0.7 a 1.8)
            factor_home = max(0.7, min(1.8, factor_home))
            lambda_home *= factor_home

        if away_goals_scored:
            avg_away = sum(away_goals_scored) / len(away_goals_scored)
            factor_away = avg_away / MEDIA_GLOBAL
            factor_away = max(0.7, min(1.8, factor_away))
            lambda_away *= factor_away

        # Volver a aplicar límites
        lambda_home = safe_lambda(lambda_home)
        lambda_away = safe_lambda(lambda_away)

    sentiment_data = None

    if use_sentiment:
        lambda_home, lambda_away, sentiment_data = await apply_sentiment(
            home, away, lambda_home, lambda_away
        )

    probs, top_scores = dixon_coles_probabilities(lambda_home, lambda_away)
    best_score = top_scores[0]["score"]
    h, a = map(int, best_score.split("-"))

    if probs["home_win"] > probs["draw"] and probs["home_win"] > probs["away_win"]:
        model_winner = home
        model_winner_code = "home"
    elif probs["away_win"] > probs["draw"]:
        model_winner = away
        model_winner_code = "away"
    else:
        model_winner = "Empate"
        model_winner_code = "draw"

    model_confidence = calculate_confidence(probs)

    odds_data = {}
    if use_odds:
        odds_data = await get_enriched_odds(home, away)

    # Generar texto de historial
    recent_home_text = format_recent_matches(home, recent_home) if recent_home else "No disponible"
    recent_away_text = format_recent_matches(away, recent_away) if recent_away else "No disponible"

    analysis = await generate_groq_analysis(
        home_team=home,
        away_team=away,
        date=match.get("date", ""),
        stage=base.get("stage", ""),
        model_probs=probs,
        model_score=best_score,
        model_winner=model_winner,
        model_winner_code=model_winner_code,
        model_confidence=model_confidence,
        model_xg_home=lambda_home,
        model_xg_away=lambda_away,
        odds_data=odds_data,
        sentiment_data=sentiment_data,
        recent_home_text=recent_home_text,
        recent_away_text=recent_away_text
    )

    # Incluir historial reciente en la respuesta (estructurado)
    recent_home_summary = summarize_recent_matches(recent_home, home) if recent_home else []
    recent_away_summary = summarize_recent_matches(recent_away, away) if recent_away else []

    prediction = {
        "match_id": match["match_id"],
        "home_team": home,
        "away_team": away,
        "date": match.get("date"),
        "stage": base.get("stage", ""),
        "model_prediction": {
            "winner": model_winner,
            "winner_code": model_winner_code,
            "score": best_score,
            "score_numeric": {"home": h, "away": a},
            "confidence": model_confidence,
            "probabilities": probs,
            "top_scores": top_scores[:3],
            "xg_home": round(lambda_home, 2),
            "xg_away": round(lambda_away, 2),
            "elo_home": round(base["elo_home"], 1),
            "elo_away": round(base["elo_away"], 1),
        },
        "odds": odds_data,
        "analysis": analysis,
        "sentiment": sentiment_data,
        "recent_home_matches": recent_home_summary,
        "recent_away_matches": recent_away_summary,
        "model_version": MODEL_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }

    return prediction


# ============================================================================
# FUNCIONES BATCH
# ============================================================================

async def update_upcoming_predictions():
    matches = await fetch_upcoming_matches()
    if not matches:
        return {"updated": 0}

    # Obtener partidos finalizados para el historial
    all_matches = await fetch_all_matches()
    finished = [m for m in all_matches if m.get("status") == "finished" and m.get("home_score") is not None]

    updated = 0
    for match in matches:
        try:
            home = match["home_team"]
            away = match["away_team"]
            home_matches = [fm for fm in finished if fm["home_team"] == home or fm["away_team"] == home]
            away_matches = [fm for fm in finished if fm["home_team"] == away or fm["away_team"] == away]
            recent_home = home_matches[:5]
            recent_away = away_matches[:5]

            pred = await generate_prediction(
                match,
                use_sentiment=True,
                use_odds=True,
                recent_home=recent_home,
                recent_away=recent_away
            )
            cache_set(f"pred:{match['match_id']}", pred, 12 * 3600)
            updated += 1
        except Exception as e:
            print(f"Error generando predicción para {match.get('match_id')}: {e}")

    return {"updated": updated}


async def process_all_finished_matches(force_reprocess: bool = False) -> dict:
    all_matches = await fetch_all_matches()
    finished = [m for m in all_matches if m.get("status") == "finished" and m.get("home_score") is not None]
    finished.sort(key=lambda x: x["date"])

    if not finished:
        return {"message": "No hay partidos finalizados en la API."}

    processed_ids = set()
    if redis_client:
        try:
            raw_ids = redis_client.smembers(PROCESSED_MATCHES_KEY)
            processed_ids = {mid.decode('utf-8') for mid in raw_ids}
        except Exception as e:
            print(f"Error leyendo Redis: {e}")

    learned = 0
    skipped = 0
    changes = []

    for match in finished:
        mid = match["match_id"]
        if mid in processed_ids and not force_reprocess:
            skipped += 1
            continue

        home = match["home_team"]
        away = match["away_team"]
        country = match.get("country", "")
        is_host = is_host_team(home, country)

        change = elo_manager.update_match(
            home_team=home,
            away_team=away,
            home_goals=match["home_score"],
            away_goals=match["away_score"],
            is_host_match=is_host
        )
        change["match_id"] = mid
        change["date"] = match["date"]
        changes.append(change)

        if redis_client:
            try:
                redis_client.sadd(PROCESSED_MATCHES_KEY, mid)
            except Exception as e:
                print(f"Error guardando en Redis: {e}")

        learned += 1

    elo_manager.save()

    regen = await update_upcoming_predictions()

    return {
        "message": f"Procesados {learned} partidos nuevos (saltados {skipped} ya existentes).",
        "learned": learned,
        "skipped": skipped,
        "total_finished": len(finished),
        "changes": changes[:20],
        "changes_count": len(changes),
        "regenerated_predictions": regen["updated"]
    }


async def recalculate_all_elo() -> dict:
    elo_manager.reset_to_initial()
    elo_manager.save()

    if redis_client:
        try:
            redis_client.delete(PROCESSED_MATCHES_KEY)
            print("🗑️ Registro de procesados eliminado de Redis.")
        except Exception as e:
            print(f"Error limpiando Redis: {e}")

    result = await process_all_finished_matches(force_reprocess=True)
    result["message"] = "Recálculo completo finalizado. " + result.get("message", "")
    return result


# Mantenemos esta función para compatibilidad
async def learn_from_recent_matches():
    return await process_all_finished_matches(force_reprocess=False)
