from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.cache.redis_client import cache_get, cache_set
from app.data.fetcher import fetch_upcoming_matches, fetch_all_matches, get_teams, get_stadiums
from app.services.prediction_service import generate_prediction, update_upcoming_predictions, process_all_finished_matches, recalculate_all_elo, elo_manager
from app.services.news_service import summarize_headlines, fetch_match_news_summary
from app.data.parser import fetch_news_headlines
import asyncio, datetime

router = APIRouter(prefix="/api/v1")

class MatchResultInput(BaseModel):
    home_team: str; away_team: str; home_goals: int; away_goals: int

def safe_match_sort(match):
    try: return int(match.get("match_id", 0))
    except: return 0

def get_today_dates():
    today = datetime.date.today()
    return today.isoformat(), (today + datetime.timedelta(days=1)).isoformat()

@router.get("/matches/upcoming")
async def upcoming_matches():
    matches = await fetch_upcoming_matches()
    matches.sort(key=safe_match_sort)
    matches = matches[:5]
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
        m["home_news"] = hn; m["away_news"] = an; m["match_news"] = mn
        return m
    enriched = await asyncio.gather(*(enrich(m) for m in matches))
    return enriched

@router.get("/predictions/today")
async def get_today_predictions():
    today, tomorrow = get_today_dates()
    upcoming = await fetch_upcoming_matches()
    matches = [m for m in upcoming if m["date"] == today]
    target = today
    if not matches:
        all_m = await fetch_all_matches()
        matches = [m for m in all_m if m["date"] == today]
    if not matches:
        matches = [m for m in upcoming if m["date"] == tomorrow]
        target = tomorrow
    fallback = False
    if not matches:
        matches = upcoming[:5]
        fallback = True
        if matches: target = matches[0]["date"]
    if not matches:
        return {"date": today, "matches": [], "count": 0, "message": "No hay partidos disponibles"}

    matches.sort(key=safe_match_sort)
    async def process_match(m):
        key = f"pred:{m['match_id']}"
        cached = cache_get(key)
        if cached: return cached
        try:
            pred = await generate_prediction(m, use_sentiment=True, use_odds=True)
            cache_set(key, pred, 12*3600)
            return pred
        except Exception as e:
            return {"match_id": m["match_id"], "error": str(e)}
    predictions = await asyncio.gather(*(process_match(m) for m in matches))
    return {"date": target, "matches": predictions, "count": len(predictions), "fallback": fallback}

@router.get("/predictions/{match_id}")
async def get_prediction(match_id: str):
    cached = cache_get(f"pred:{match_id}")
    if not cached: raise HTTPException(404, "Predicción no disponible")
    return cached

@router.post("/predictions/refresh")
async def refresh_predictions():
    result = await update_upcoming_predictions()
    return {"status": "ok", "updated": result.get("updated", 0)}

@router.post("/predictions/learn")
async def learn_predictions():
    result = await process_all_finished_matches(force_reprocess=False)
    return {"status": "ok", **result}

@router.post("/predictions/recalculate")
async def recalculate_predictions():
    result = await recalculate_all_elo()
    return {"status": "ok", **result}

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
