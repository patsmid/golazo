from fastapi import APIRouter, HTTPException
from app.services.worldcup_service import (
    get_wc_groups, get_wc_group,
    get_wc_games, get_wc_game,
    get_wc_teams, get_wc_team,
    get_wc_stadiums, get_wc_health
)

router = APIRouter(prefix="/api/v1/worldcup")

# ============================================================================
# GRUPOS (con nombres en español y flags)
# ============================================================================

@router.get("/groups")
async def wc_groups():
    """
    Todos los grupos con standings.

    Cada equipo incluye: `name_es`, `name_en`, `flag`, `fifa_code`
    Cache: 2 min.
    """
    data = await get_wc_groups()
    if not data:
        raise HTTPException(503, "No se pudo obtener datos de grupos desde worldcup26.ir")
    return data

@router.get("/groups/{group_id}")
async def wc_group(group_id: str):
    """
    Un grupo específico.

    Equipos enriquecidos con nombres en español.
    Cache: 2 min.
    """
    data = await get_wc_group(group_id)
    if not data:
        raise HTTPException(503, f"No se pudo obtener grupo {group_id}")
    return data


# ============================================================================
# PARTIDOS (con nombres en español + hora CDMX)
# ============================================================================

@router.get("/games")
async def wc_games():
    """
    Todos los partidos (104) con datos enriquecidos.

    Campos adicionales por partido:
    - `home_team_name_es` / `away_team_name_es`: Nombres en español
    - `home_team_name_original` / `away_team_name_original`: Nombres en inglés
    - `home_flag` / `away_flag`: URLs de banderas
    - `home_fifa_code` / `away_fifa_code`: Códigos FIFA
    - `time_cdmx` / `datetime_cdmx_iso`: Horario convertido a CDMX
    - `time_local` / `datetime_iso`: Horario original del estadio
    - `timezone_local` / `timezone_cdmx`: Zonas horarias
    - `stadium_name_en`, `stadium_city`, `stadium_country`, `stadium_capacity`
    - `status`: "finished" | "live" | "upcoming"
    - `home_scorers_list` / `away_scorers_list`: Array de goleadores parseados

    Cache: 1 min (live scores).
    """
    data = await get_wc_games()
    if not data:
        raise HTTPException(503, "No se pudo obtener partidos desde worldcup26.ir")
    return data

@router.get("/games/{game_id}")
async def wc_game(game_id: str):
    """
    Un partido específico con todos los campos enriquecidos.

    Cache: 1 min.
    """
    data = await get_wc_game(game_id)
    if not data:
        raise HTTPException(404, f"Partido {game_id} no encontrado")
    return data


# ============================================================================
# EQUIPOS (con nombres en español)
# ============================================================================

@router.get("/teams")
async def wc_teams():
    """
    Los 48 equipos.

    Cada equipo incluye: `name_es` (español), `name_en` (inglés), `name_original`
    Cache: 24h.
    """
    data = await get_wc_teams()
    if not data:
        raise HTTPException(503, "No se pudo obtener equipos desde worldcup26.ir")
    return data

@router.get("/teams/{team_id}")
async def wc_team(team_id: str):
    """
    Un equipo específico con nombre en español.

    Cache: 24h.
    """
    data = await get_wc_team(team_id)
    if not data:
        raise HTTPException(404, f"Equipo {team_id} no encontrado")
    return data


# ============================================================================
# ESTADIOS
# ============================================================================

@router.get("/stadiums")
async def wc_stadiums():
    """
    Los 16 estadios. Cache: 1h.
    """
    data = await get_wc_stadiums()
    if not data:
        raise HTTPException(503, "No se pudo obtener estadios desde worldcup26.ir")
    return data


# ============================================================================
# HEALTH / STATUS
# ============================================================================

@router.get("/health")
async def wc_health():
    """
    Estado de conexión con worldcup26.ir.
    """
    data = await get_wc_health()
    return {
        "source": "worldcup26.ir",
        "proxy_status": "ok" if data and data.get("status") == "healthy" else "degraded",
        "upstream": data or {"status": "unreachable"}
    }
