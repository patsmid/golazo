from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.cache.redis_client import cache_get, cache_set
from app.data.fetcher import fetch_upcoming_matches, fetch_all_matches, get_teams, get_stadiums
from app.services.prediction_service import generate_prediction, update_upcoming_predictions, process_all_finished_matches, recalculate_all_elo, elo_manager
from app.services.news_service import summarize_headlines, fetch_match_news_summary
from app.data.parser import fetch_news_headlines
from collections import defaultdict  # Añadir al inicio del archivofrom collections import defaultdict  # Añadir al inicio del archivo
import asyncio, datetime
from app.services.task_tracker import (
    start_task, complete_task, fail_task,
    generate_task_id, get_task_status
)

router = APIRouter(prefix="/api/v1")

class MatchResultInput(BaseModel):
    home_team: str; away_team: str; home_goals: int; away_goals: int

# Ordenar por fecha/hora (ascendente)
def match_datetime_sort(match):
    return match.get("datetime", match.get("date", ""))

def get_today_dates():
    today = datetime.date.today()
    return today.isoformat(), (today + datetime.timedelta(days=1)).isoformat()

@router.get("/matches/upcoming")
async def upcoming_matches():
    # Obtener todos los partidos futuros
    upcoming = await fetch_upcoming_matches()
    if not upcoming:
        return {"date": None, "matches": [], "count": 0, "message": "No hay partidos próximos"}

    # Agrupar por fecha
    from collections import defaultdict
    by_date = defaultdict(list)
    for m in upcoming:
        by_date[m["date"]].append(m)

    # Ordenar fechas y tomar la más cercana
    sorted_dates = sorted(by_date.keys())
    if not sorted_dates:
        return {"date": None, "matches": [], "count": 0, "message": "No hay partidos próximos"}

    target_date = sorted_dates[0]
    matches = by_date[target_date]

    # Ordenar por fecha/hora y ID como desempate
    matches.sort(key=lambda x: (x.get("datetime", x.get("date", "")), int(x.get("match_id", 0))))

    # Enriquecer con noticias
    async def enrich(m):
        home, away = m["home_team"], m["away_team"]
        try:
            hh, ah = await asyncio.gather(
                asyncio.to_thread(fetch_news_headlines, home),
                asyncio.to_thread(fetch_news_headlines, away)
            )
            hn, an, mn = await asyncio.gather(
                asyncio.to_thread(summarize_headlines, home, hh),
                asyncio.to_thread(summarize_headlines, away, ah),
                asyncio.to_thread(fetch_match_news_summary, home, away)
            )
        except:
            hn = an = mn = "No disponible"
        m["home_news"] = hn
        m["away_news"] = an
        m["match_news"] = mn
        return m

    enriched = await asyncio.gather(*(enrich(m) for m in matches))
    return {
        "date": target_date,
        "matches": enriched,
        "count": len(enriched)
    }

@router.get("/predictions/today")
async def get_today_predictions():
    # Obtener partidos futuros (no empezados)
    upcoming = await fetch_upcoming_matches()

    # Si no hay próximos, buscar en todos los partidos aquellos que no hayan finalizado
    if not upcoming:
        all_m = await fetch_all_matches()
        today_str = datetime.date.today().isoformat()
        upcoming = [m for m in all_m if m.get("status") != "finished" and m.get("date", "") >= today_str]

    if not upcoming:
        return {"date": None, "matches": [], "count": 0, "message": "No hay partidos próximos disponibles"}

    # Agrupar por fecha (sin hora)
    by_date = defaultdict(list)
    for m in upcoming:
        by_date[m["date"]].append(m)

    # Ordenar fechas y tomar la más cercana (la primera)
    sorted_dates = sorted(by_date.keys())
    target_date = sorted_dates[0]
    matches = by_date[target_date]

    # Ordenar por hora (datetime) dentro de la misma fecha
    matches.sort(key=lambda x: (x.get("datetime", x.get("date", "")), int(x.get("match_id", 0))))

    # --- OBTENER TODOS LOS PARTIDOS FINALIZADOS PARA EL HISTORIAL ---
    all_matches = await fetch_all_matches()
    finished = [m for m in all_matches if m.get("status") == "finished" and m.get("home_score") is not None]
    finished.sort(key=lambda x: x.get("date", ""), reverse=True)

    print(f"📊 Partidos finalizados disponibles: {len(finished)}")
    for f in finished[:3]:
        print(f"  {f['home_team']} vs {f['away_team']} - {f['home_score']}-{f['away_score']} ({f['date']})")

    async def process_match(m):
        key = f"pred:{m['match_id']}"
        cached = cache_get(key)
        # Usar caché solo si ya tiene historial
        if cached and cached.get("recent_home_matches"):
            return cached

        home = m["home_team"]
        away = m["away_team"]
        home_matches = [fm for fm in finished if fm["home_team"] == home or fm["away_team"] == home]
        away_matches = [fm for fm in finished if fm["home_team"] == away or fm["away_team"] == away]
        recent_home = home_matches[:5]
        recent_away = away_matches[:5]

        try:
            pred = await generate_prediction(m, use_sentiment=True, use_odds=True,
                                             recent_home=recent_home, recent_away=recent_away)
            cache_set(key, pred, 12*3600)
            return pred
        except Exception as e:
            return {"match_id": m["match_id"], "error": str(e)}

    predictions = await asyncio.gather(*(process_match(m) for m in matches))
    return {"date": target_date, "matches": predictions, "count": len(predictions), "fallback": False}

@router.get("/predictions/{match_id}")
async def get_prediction(match_id: str):
    cached = cache_get(f"pred:{match_id}")
    if not cached: raise HTTPException(404, "Predicción no disponible")
    return cached

@router.get("/predictions/task/{task_id}")
async def get_task_status_endpoint(task_id: str):
    """Obtiene el estado de una tarea en segundo plano."""
    status = get_task_status(task_id)
    if not status:
        raise HTTPException(404, "Tarea no encontrada o expirada")
    return status

@router.post("/predictions/refresh")
async def refresh_predictions():
    task_id = generate_task_id()
    start_task(task_id, "refresh", {"type": "refresh_predictions"})

    async def run_refresh():
        try:
            result = await update_upcoming_predictions()
            complete_task(task_id, result)
        except Exception as e:
            fail_task(task_id, str(e))

    asyncio.create_task(run_refresh())
    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "Actualización de predicciones iniciada en segundo plano. Consulta /predictions/task/{task_id} para ver el progreso."
    }

@router.post("/predictions/learn")
async def learn_predictions():
    task_id = generate_task_id()
    start_task(task_id, "learn", {"type": "learn_from_results"})

    async def run_learn():
        try:
            result = await process_all_finished_matches(force_reprocess=False)
            complete_task(task_id, result)
        except Exception as e:
            fail_task(task_id, str(e))

    asyncio.create_task(run_learn())
    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "Aprendizaje iniciado en segundo plano. Consulta /predictions/task/{task_id} para ver el progreso."
    }

@router.post("/predictions/recalculate")
async def recalculate_predictions():
    task_id = generate_task_id()
    start_task(task_id, "recalculate", {"type": "recalculate_elo"})

    async def run_recalculate():
        try:
            result = await recalculate_all_elo()
            complete_task(task_id, result)
        except Exception as e:
            fail_task(task_id, str(e))

    asyncio.create_task(run_recalculate())
    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "Recálculo completo iniciado en segundo plano. Consulta /predictions/task/{task_id} para ver el progreso."
    }

@router.get("/predictions/tasks/recent")
async def get_recent_tasks(limit: int = 10):
    """Obtiene las tareas más recientes."""
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
