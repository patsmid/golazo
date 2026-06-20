from fastapi import APIRouter, BackgroundTasks
from app.services.prediction_service import update_upcoming_predictions
from app.data.fetcher import fetch_recent_results
from app.models.elo import EloManager

router = APIRouter(prefix="/api/v1/admin")
elo = EloManager()

@router.post("/update_predictions")
async def trigger_update(background_tasks: BackgroundTasks):
    """Endpoint que llama el cron externo cada 1-2 horas."""
    background_tasks.add_task(update_upcoming_predictions)
    return {"status": "Update triggered"}

@router.post("/update_ratings")
async def update_ratings():
    """Actualiza Elo con los resultados recientes y limpia caché de predicciones."""
    results = await fetch_recent_results()
    for r in results:
        elo.update_match(
            home_team=r["home_team"],
            away_team=r["away_team"],
            home_goals=r["home_goals"],
            away_goals=r["away_goals"]
        )
    return {"status": "Elo updated", "matches_processed": len(results)}
