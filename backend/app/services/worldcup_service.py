import httpx
import json
from typing import Optional, Dict, Any
from app.cache.redis_client import cache_get, cache_set

WC26_BASE = "https://worldcup26.ir"

# TTLs de caché (segundos)
CACHE_TTLS = {
    "wc26:groups": 120,      # 2 min - standings cambian con cada partido
    "wc26:games": 60,        # 1 min - scores en vivo
    "wc26:teams": 86400,     # 24h - equipos no cambian
    "wc26:stadiums": 3600,   # 1h - estadios no cambian
    "wc26:game:": 60,        # 1 min por partido
    "wc26:team:": 86400,     # 24h por equipo
    "wc26:group:": 120,      # 2 min por grupo
}

async def _fetch_wc26(path: str, cache_key: str, ttl: int) -> Optional[Dict[str, Any]]:
    """Fetch con caché Redis."""
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{WC26_BASE}{path}")
            resp.raise_for_status()
            data = resp.json()
            cache_set(cache_key, data, ttl)
            return data
    except Exception as e:
        print(f"⚠️ Error fetching worldcup26.ir{path}: {e}")
        return None


# ============================================================================
# GRUPOS
# ============================================================================

async def get_wc_groups() -> Optional[Dict]:
    return await _fetch_wc26("/get/groups", "wc26:groups", CACHE_TTLS["wc26:groups"])

async def get_wc_group(group_id: str) -> Optional[Dict]:
    return await _fetch_wc26(f"/get/group/{group_id}", f"wc26:group:{group_id}", CACHE_TTLS["wc26:group:"])


# ============================================================================
# PARTIDOS (GAMES)
# ============================================================================

async def get_wc_games() -> Optional[Dict]:
    return await _fetch_wc26("/get/games", "wc26:games", CACHE_TTLS["wc26:games"])

async def get_wc_game(game_id: str) -> Optional[Dict]:
    return await _fetch_wc26(f"/get/game/{game_id}", f"wc26:game:{game_id}", CACHE_TTLS["wc26:game:"])


# ============================================================================
# EQUIPOS
# ============================================================================

async def get_wc_teams() -> Optional[Dict]:
    return await _fetch_wc26("/get/teams", "wc26:teams", CACHE_TTLS["wc26:teams"])

async def get_wc_team(team_id: str) -> Optional[Dict]:
    return await _fetch_wc26(f"/get/team/{team_id}", f"wc26:team:{team_id}", CACHE_TTLS["wc26:team:"])


# ============================================================================
# ESTADIOS
# ============================================================================

async def get_wc_stadiums() -> Optional[Dict]:
    return await _fetch_wc26("/get/stadiums", "wc26:stadiums", CACHE_TTLS["wc26:stadiums"])


# ============================================================================
# HEALTH
# ============================================================================

async def get_wc_health() -> Optional[Dict]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{WC26_BASE}/health")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}
