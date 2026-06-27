from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.cache.redis_client import cache_get, cache_set, redis_client
from app.data.fetcher import fetch_upcoming_matches, fetch_all_matches, get_teams, get_stadiums
from app.services.prediction_service import generate_prediction, update_upcoming_predictions, process_all_finished_matches, recalculate_all_elo, elo_manager
from app.services.news_service import summarize_headlines, fetch_match_news_summary, generate_match_analysis
from app.data.parser import fetch_news_headlines
from collections import defaultdict
import asyncio, datetime, json
from app.services.task_tracker import (
    start_task, complete_task, fail_task,
    generate_task_id, get_task_status, TASK_PREFIX
)

router = APIRouter(prefix="/api/v1")

class MatchResultInput(BaseModel):
    home_team: str; away_team: str; home_goals: int; away_goals: int

# ============================================================================
# MATCHES / UPCOMING  —  RÁPIDO, SIN GROQ
# ============================================================================

@router.get("/matches/upcoming")
async def upcoming_matches():
    """Endpoint rápido: datos de partidos + noticias cacheadas (0 llamadas Groq)."""
    cache_key = "wc2026:upcoming:v2"
    cached = cache_get(cache_key)
    if cached:
        return cached

    upcoming = await fetch_upcoming_matches()
    if not upcoming:
        return {"date": None, "matches": [], "count": 0, "message": "No hay partidos próximos"}

    by_date = defaultdict(list)
    for m in upcoming:
        by_date[m["date"]].append(m)

    sorted_dates = sorted(by_date.keys())
    if not sorted_dates:
        return {"date": None, "matches": [], "count": 0}

    target_date = sorted_dates[0]
    matches = by_date[target_date]
    matches.sort(key=lambda x: (x.get("datetime", ""), int(x.get("match_id", 0))))

    # Agregar noticias solo si están cacheadas (sin llamar Groq)
    for m in matches:
        news = cache_get(f"wc2026:news:{m['match_id']}")
        if news:
            m["home_news"] = news.get("home_news", "")
            m["away_news"] = news.get("away_news", "")
            m["match_news"] = news.get("match_news", "")
            m["has_ai_news"] = True
        else:
            m["home_news"] = ""
            m["away_news"] = ""
            m["match_news"] = ""
            m["has_ai_news"] = False

    result = {"date": target_date, "matches": matches, "count": len(matches)}

    # Cache por 10 minutos
    cache_set(cache_key, result, 600)
    return result


# ============================================================================
# PRELOAD NOTICIAS  —  TAREA EN FONDO
# ============================================================================

@router.post("/matches/preload-news")
async def preload_news():
    """Precarga noticias + resúmenes Groq para todos los partidos próximos."""
    task_id = generate_task_id()
    start_task(task_id, "preload_news", {"type": "preload_news"})

    async def run():
        try:
            upcoming = await fetch_upcoming_matches()
            if not upcoming:
                complete_task(task_id, {"preloaded": 0, "total": 0})
                return

            preloaded = 0
            for m in upcoming:
                mid = m["match_id"]
                # Saltar si ya tiene noticias cacheadas
                if cache_get(f"wc2026:news:{mid}"):
                    preloaded += 1
                    continue

                home, away = m["home_team"], m["away_team"]
                try:
                    hh, ah = await asyncio.gather(
                        asyncio.to_thread(fetch_news_headlines, home),
                        asyncio.to_thread(fetch_news_headlines, away)
                    )
                    hn = await asyncio.to_thread(summarize_headlines, home, hh)
                    an = await asyncio.to_thread(summarize_headlines, away, ah)
                    mn = await asyncio.to_thread(fetch_match_news_summary, home, away)

                    cache_set(f"wc2026:news:{mid}", {
                        "home_news": hn, "away_news": an, "match_news": mn
                    }, 7200)
                    preloaded += 1
                except Exception as e:
                    print(f"⚠️ Error noticias {mid}: {e}")

                # Pausa para no saturar Groq rate limits
                await asyncio.sleep(1)

            # Invalidar caché de upcoming para que incluya las noticias nuevas
            try:
                redis_client.delete("wc2026:upcoming:v2")
            except Exception:
                pass

            complete_task(task_id, {"preloaded": preloaded, "total": len(upcoming)})
        except Exception as e:
            fail_task(task_id, str(e))

    asyncio.create_task(run())
    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "Precarga de noticias iniciada. Llama /matches/upcoming despues de unos segundos."
    }


# ============================================================================
# AI ANALYSIS  —  BAJO DEMANDA, MEJOR MODELO
# ============================================================================

@router.get("/matches/{match_id}/ai-analysis")
async def get_match_ai_analysis(match_id: str, force_refresh: bool = False):
    """Análisis IA profundo bajo demanda (llama-3.3-70b-versatile)."""
    cache_key = f"wc2026:ai:{match_id}"

    if not force_refresh:
        cached = cache_get(cache_key)
        if cached:
            return cached

    # Buscar el partido
    upcoming = await fetch_upcoming_matches()
    match = next((m for m in upcoming if m["match_id"] == match_id), None)
    if not match:
        all_m = await fetch_all_matches()
        match = next((m for m in all_m if m["match_id"] == match_id), None)
    if not match:
        raise HTTPException(404, "Partido no encontrado")

    home, away = match["home_team"], match["away_team"]

    # Obtener noticias RSS
    try:
        hh, ah = await asyncio.gather(
            asyncio.to_thread(fetch_news_headlines, home),
            asyncio.to_thread(fetch_news_headlines, away)
        )
    except Exception:
        hh, ah = [], []

    # Generar análisis con el mejor modelo
    analysis = await asyncio.to_thread(
        generate_match_analysis, home, away, hh, ah, match
    )

    # Cache por 4 horas
    cache_set(cache_key, analysis, 4 * 3600)

    # También guardar resúmenes cortos en caché de noticias del partido
    cache_set(f"wc2026:news:{match_id}", {
        "home_news": analysis.get("home_summary", ""),
        "away_news": analysis.get("away_summary", ""),
        "match_news": analysis.get("match_preview", "")
    }, 7200)

    # Invalidar caché de upcoming
    try:
        redis_client.delete("wc2026:upcoming:v2")
    except Exception:
        pass

    return analysis


@router.post("/matches/preload-ai-all")
async def preload_ai_all():
    """Precarga análisis IA profundo para todos los partidos próximos."""
    task_id = generate_task_id()
    start_task(task_id, "preload_ai", {"type": "preload_ai_all"})

    async def run():
        try:
            upcoming = await fetch_upcoming_matches()
            if not upcoming:
                complete_task(task_id, {"preloaded": 0, "total": 0})
                return

            preloaded = 0
            for m in upcoming:
                mid = m["match_id"]
                if cache_get(f"wc2026:ai:{mid}"):
                    preloaded += 1
                    continue

                home, away = m["home_team"], m["away_team"]
                try:
                    hh, ah = await asyncio.gather(
                        asyncio.to_thread(fetch_news_headlines, home),
                        asyncio.to_thread(fetch_news_headlines, away)
                    )
                    analysis = await asyncio.to_thread(
                        generate_match_analysis, home, away, hh, ah, m
                    )
                    cache_set(f"wc2026:ai:{mid}", analysis, 4 * 3600)
                    cache_set(f"wc2026:news:{mid}", {
                        "home_news": analysis.get("home_summary", ""),
                        "away_news": analysis.get("away_summary", ""),
                        "match_news": analysis.get("match_preview", "")
                    }, 7200)
                    preloaded += 1
                except Exception as e:
                    print(f"⚠️ Error IA {mid}: {e}")

                await asyncio.sleep(2)  # Más pausa para el modelo grande

            try:
                redis_client.delete("wc2026:upcoming:v2")
            except Exception:
                pass

            complete_task(task_id, {"preloaded": preloaded, "total": len(upcoming)})
        except Exception as e:
            fail_task(task_id, str(e))

    asyncio.create_task(run())
    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "Análisis IA profundo iniciado para todos los partidos."
    }


# ============================================================================
# PREDICTIONS  —  SIN CAMBIOS (ya usan caché propio)
# ============================================================================

@router.get("/predictions/today")
async def get_today_predictions():
    upcoming = await fetch_upcoming_matches()
    if not upcoming:
        all_m = await fetch_all_matches()
        today_str = datetime.date.today().isoformat()
        upcoming = [m for m in all_m if m.get("status") != "finished" and m.get("date", "") >= today_str]
    if not upcoming:
        return {"date": None, "matches": [], "count": 0, "message": "No hay partidos próximos"}

    by_date = defaultdict(list)
    for m in upcoming:
        by_date[m["date"]].append(m)
    sorted_dates = sorted(by_date.keys())
    target_date = sorted_dates[0]
    matches = by_date[target_date]
    matches.sort(key=lambda x: (x.get("datetime", ""), int(x.get("match_id", 0))))

    all_matches = await fetch_all_matches()
    finished = [m for m in all_matches if m.get("status") == "finished" and m.get("home_score") is not None]
    finished.sort(key=lambda x: x.get("date", ""), reverse=True)

    print(f"📊 Partidos finalizados disponibles: {len(finished)}")

    async def process_match(m):
        key = f"pred:{m['match_id']}"
        cached = cache_get(key)
        if cached and cached.get("recent_home_matches"):
            return cached
        home, away = m["home_team"], m["away_team"]
        home_matches = [fm for fm in finished if fm["home_team"] == home or fm["away_team"] == home]
        away_matches = [fm for fm in finished if fm["home_team"] == away or fm["away_team"] == away]
        try:
            pred = await generate_prediction(m, use_sentiment=True, use_odds=True,
                                             recent_home=home_matches[:5], recent_away=away_matches[:5])
            cache_set(key, pred, 12 * 3600)
            return pred
        except Exception as e:
            return {"match_id": m["match_id"], "error": str(e)}

    predictions = await asyncio.gather(*(process_match(m) for m in matches))
    return {"date": target_date, "matches": predictions, "count": len(predictions), "fallback": False}

@router.get("/predictions/{match_id}")
async def get_prediction(match_id: str):
    cached = cache_get(f"pred:{match_id}")
    if not cached:
        raise HTTPException(404, "Predicción no disponible")
    return cached

@router.get("/predictions/task/{task_id}")
async def get_task_status_endpoint(task_id: str):
    status = get_task_status(task_id)
    if not status:
        raise HTTPException(404, "Tarea no encontrada o expirada")
    return status

@router.post("/predictions/refresh")
async def refresh_predictions():
    task_id = generate_task_id()
    start_task(task_id, "refresh", {"type": "refresh_predictions"})
    async def run():
        try:
            result = await update_upcoming_predictions()
            complete_task(task_id, result)
        except Exception as e:
            fail_task(task_id, str(e))
    asyncio.create_task(run())
    return {"status": "accepted", "task_id": task_id, "message": "Actualización iniciada."}

@router.post("/predictions/learn")
async def learn_predictions():
    task_id = generate_task_id()
    start_task(task_id, "learn", {"type": "learn"})
    async def run():
        try:
            result = await process_all_finished_matches(force_reprocess=False)
            complete_task(task_id, result)
        except Exception as e:
            fail_task(task_id, str(e))
    asyncio.create_task(run())
    return {"status": "accepted", "task_id": task_id, "message": "Aprendizaje iniciado."}

@router.post("/predictions/recalculate")
async def recalculate_predictions():
    task_id = generate_task_id()
    start_task(task_id, "recalculate", {"type": "recalculate"})
    async def run():
        try:
            result = await recalculate_all_elo()
            complete_task(task_id, result)
        except Exception as e:
            fail_task(task_id, str(e))
    asyncio.create_task(run())
    return {"status": "accepted", "task_id": task_id, "message": "Recálculo iniciado."}

@router.get("/predictions/tasks/recent")
async def get_recent_tasks(limit: int = 10):
    keys = redis_client.keys(f"{TASK_PREFIX}*")
    tasks = []
    for key in sorted(keys, reverse=True)[:limit]:
        data = redis_client.get(key)
        if data:
            tasks.append(json.loads(data))
    return {"tasks": tasks}

@router.post("/matches/result")
async def report_match_result(data: MatchResultInput):
    try:
        change = elo_manager.update_match(data.home_team, data.away_team, data.home_goals, data.away_goals, is_host_match=False)
        return {"status": "ok", "change": change}
    except Exception as e:
        raise HTTPException(400, str(e))

@router.get("/teams")
async def teams():
    try:
        data = await get_teams()
        return {"teams": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/stadiums")
async def stadiums():
    try:
        data = await get_stadiums()
        return {"stadiums": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(500, str(e))
