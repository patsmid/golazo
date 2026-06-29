from fastapi import APIRouter, HTTPException
from app.services.worldcup_service import (
    get_wc_groups, get_wc_group,
    get_wc_games, get_wc_game,
    get_wc_teams, get_wc_team,
    get_wc_stadiums, get_wc_health
)

router = APIRouter(prefix="/api/v1/worldcup")

# ============================================================================
# GRUPOS
# ============================================================================

@router.get("/groups")
async def wc_groups():
    """Todos los grupos con standings. Cache: 2 min."""
    data = await get_wc_groups()
    if not data:
        raise HTTPException(503, "No se pudo obtener datos de grupos desde worldcup26.ir")
    return data

@router.get("/groups/{group_id}")
async def wc_group(group_id: str):
    """Un grupo específico. Cache: 2 min."""
    data = await get_wc_group(group_id)
    if not data:
        raise HTTPException(503, f"No se pudo obtener grupo {group_id}")
    return data


# ============================================================================
# PARTIDOS
# ============================================================================

@router.get("/games")
async def wc_games():
    """Todos los partidos (104). Cache: 1 min (live scores)."""
    data = await get_wc_games()
    if not data:
        raise HTTPException(503, "No se pudo obtener partidos desde worldcup26.ir")
    return data

@router.get("/games/{game_id}")
async def wc_game(game_id: str):
    """Un partido específico. Cache: 1 min."""
    data = await get_wc_game(game_id)
    if not data:
        raise HTTPException(404, f"Partido {game_id} no encontrado")
    return data


# ============================================================================
# EQUIPOS
# ============================================================================

@router.get("/teams")
async def wc_teams():
    """Todos los 48 equipos. Cache: 24h."""
    data = await get_wc_teams()
    if not data:
        raise HTTPException(503, "No se pudo obtener equipos desde worldcup26.ir")
    return data

@router.get("/teams/{team_id}")
async def wc_team(team_id: str):
    """Un equipo específico. Cache: 24h."""
    data = await get_wc_team(team_id)
    if not data:
        raise HTTPException(404, f"Equipo {team_id} no encontrado")
    return data


# ============================================================================
# ESTADIOS
# ============================================================================

@router.get("/stadiums")
async def wc_stadiums():
    """Todos los 16 estadios. Cache: 1h."""
    data = await get_wc_stadiums()
    if not data:
        raise HTTPException(503, "No se pudo obtener estadios desde worldcup26.ir")
    return data


# ============================================================================
# HEALTH / STATUS
# ============================================================================

@router.get("/health")
async def wc_health():
    """Estado de conexión con worldcup26.ir."""
    data = await get_wc_health()
    return {
        "source": "worldcup26.ir",
        "proxy_status": "ok" if data and data.get("status") == "healthy" else "degraded",
        "upstream": data or {"status": "unreachable"}
    }
