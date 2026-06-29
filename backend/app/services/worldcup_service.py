import httpx
import datetime
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
from app.cache.redis_client import cache_get, cache_set

WC26_BASE = "https://worldcup26.ir"

# ============================================================================
# MAPEO DE NOMBRES A ESPAÑOL (del fetcher.py original)
# ============================================================================
TEAM_NAME_MAP = {
    "Australia": "Australia", "Turkey": "Turquía", "Qatar": "Catar",
    "Switzerland": "Suiza", "United States": "Estados Unidos", "Germany": "Alemania",
    "Ivory Coast": "Costa de Marfil", "Netherlands": "Países Bajos", "Sweden": "Suecia",
    "France": "Francia", "Iraq": "Irak", "Norway": "Noruega", "Senegal": "Senegal",
    "Japan": "Japón", "Tunisia": "Túnez", "Haiti": "Haití", "Scotland": "Escocia",
    "England": "Inglaterra", "Croatia": "Croacia", "Spain": "España",
    "Saudi Arabia": "Arabia Saudita", "Jordan": "Jordania", "Algeria": "Argelia",
    "Portugal": "Portugal", "Uzbekistan": "Uzbekistán", "Panama": "Panamá",
    "Czech Republic": "República Checa", "Mexico": "México", "South Korea": "Corea del Sur",
    "Paraguay": "Paraguay", "Morocco": "Marruecos", "Brazil": "Brasil", "Canada": "Canadá",
    "Bosnia and Herzegovina": "Bosnia y Herzegovina", "Belgium": "Bélgica", "Iran": "Irán",
    "Egypt": "Egipto", "New Zealand": "Nueva Zelanda", "Cape Verde": "Cabo Verde",
    "Uruguay": "Uruguay", "Austria": "Austria", "Argentina": "Argentina",
    "Colombia": "Colombia", "Democratic Republic of the Congo": "Rep. Dem. del Congo",
    "Ecuador": "Ecuador", "Curaçao": "Curazao", "South Africa": "Sudáfrica", "Ghana": "Ghana",
    "Italia": "Italia", "Polonia": "Polonia", "Serbia": "Serbia", "Dinamarca": "Dinamarca",
    "Perú": "Perú", "Chile": "Chile", "Camerún": "Camerún", "Nigeria": "Nigeria",
    "Costa Rica": "Costa Rica",
}

# ============================================================================
# ZONAS HORARIAS POR ESTADIO (del fetcher.py original)
# ============================================================================
STADIUM_TIMEZONES = {
    "1": "America/Mexico_City", "2": "America/Mexico_City", "3": "America/Mexico_City",
    "4": "America/Chicago",     "5": "America/Chicago",     "6": "America/Chicago",
    "7": "America/New_York",    "8": "America/New_York",    "9": "America/New_York",
    "10": "America/New_York",   "11": "America/New_York",   "12": "America/Toronto",
    "13": "America/Vancouver",  "14": "America/Los_Angeles", "15": "America/Los_Angeles",
    "16": "America/Los_Angeles",
}

MEXICO_TZ = ZoneInfo("America/Mexico_City")

# ============================================================================
# CACHE TTLs
# ============================================================================
CACHE_TTLS = {
    "wc26:groups": 120, "wc26:games": 60, "wc26:teams": 86400,
    "wc26:stadiums": 3600, "wc26:game:": 60, "wc26:team:": 86400, "wc26:group:": 120,
}

# ============================================================================
# HELPERS
# ============================================================================

def _map_team(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name)

def _parse_scorers(scorers_str: str) -> List[str]:
    """Parsea el string de goleadores de worldcup26.ir."""
    if not scorers_str or scorers_str == "null":
        return []
    try:
        # Viene como: {"J. Quiñones 9'","R. Jiménez 67'"}
        s = scorers_str.strip()
        if s.startswith("{") and s.endswith("}"):
            s = s[1:-1]
        items = []
        for item in s.split('","'):
            item = item.strip().strip('"').strip("'")
            if item:
                items.append(item)
        return items
    except Exception:
        return []

def _convert_to_cdmx(local_date_str: str, stadium_id: str) -> Dict[str, Any]:
    """Convierte fecha local del estadio a CDMX."""
    try:
        dt = datetime.datetime.strptime(local_date_str, "%m/%d/%Y %H:%M")
        stadium_tz_str = STADIUM_TIMEZONES.get(str(stadium_id), "America/Mexico_City")
        stadium_tz = ZoneInfo(stadium_tz_str)
        dt_with_tz = dt.replace(tzinfo=stadium_tz)
        dt_mx = dt_with_tz.astimezone(MEXICO_TZ)
        return {
            "date_iso": dt.date().isoformat(),
            "time_local": dt.strftime("%H:%M"),
            "time_cdmx": dt_mx.strftime("%H:%M"),
            "datetime_iso": dt.isoformat(),
            "datetime_cdmx_iso": dt_mx.isoformat(),
            "timezone_local": stadium_tz_str,
            "timezone_cdmx": "America/Mexico_City",
        }
    except Exception:
        return {
            "date_iso": "",
            "time_local": "",
            "time_cdmx": "",
            "datetime_iso": "",
            "datetime_cdmx_iso": "",
            "timezone_local": "",
            "timezone_cdmx": "America/Mexico_City",
        }

def _determine_status(game: Dict) -> str:
    """Determina el estado del partido."""
    finished = game.get("finished") == "TRUE"
    time_elapsed = game.get("time_elapsed", "notstarted")
    if finished:
        return "finished"
    if time_elapsed and time_elapsed != "notstarted" and time_elapsed != "Finished":
        return "live"
    return "upcoming"

# ============================================================================
# FETCH CON CACHE
# ============================================================================

async def _fetch_wc26(path: str, cache_key: str, ttl: int) -> Optional[Dict[str, Any]]:
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
# EQUIPOS (con nombres en español)
# ============================================================================

async def get_wc_teams() -> Optional[Dict]:
    data = await _fetch_wc26("/get/teams", "wc26:teams", CACHE_TTLS["wc26:teams"])
    if not data or "teams" not in data:
        return None

    # Enriquecer con nombres en español
    enriched = []
    for t in data["teams"]:
        name_en = t.get("name_en", "")
        enriched.append({
            **t,
            "name_es": _map_team(name_en),
            "name_original": name_en,
        })
    return {"teams": enriched, "count": len(enriched)}

async def get_wc_team(team_id: str) -> Optional[Dict]:
    data = await _fetch_wc26(f"/get/team/{team_id}", f"wc26:team:{team_id}", CACHE_TTLS["wc26:team:"])
    if not data:
        return None
    team = data.get("team", data)
    if team:
        name_en = team.get("name_en", "")
        team["name_es"] = _map_team(name_en)
        team["name_original"] = name_en
    return data


# ============================================================================
# GRUPOS (con nombres en español)
# ============================================================================

async def get_wc_groups() -> Optional[Dict]:
    data = await _fetch_wc26("/get/groups", "wc26:groups", CACHE_TTLS["wc26:groups"])
    if not data or "groups" not in data:
        return None

    # Precargar equipos para enriquecer nombres
    teams_data = await get_wc_teams()
    teams_map = {}
    if teams_data:
        for t in teams_data.get("teams", []):
            teams_map[t.get("id", "")] = t

    enriched_groups = []
    for g in data["groups"]:
        enriched_teams = []
        for team_entry in g.get("teams", []):
            team_id = team_entry.get("team_id", "")
            team_info = teams_map.get(team_id, {})
            enriched_teams.append({
                **team_entry,
                "name_en": team_info.get("name_en", ""),
                "name_es": team_info.get("name_es", _map_team(team_info.get("name_en", ""))),
                "flag": team_info.get("flag", ""),
                "fifa_code": team_info.get("fifa_code", ""),
            })
        enriched_groups.append({
            **g,
            "teams": enriched_teams,
        })

    return {"groups": enriched_groups, "count": len(enriched_groups)}

async def get_wc_group(group_id: str) -> Optional[Dict]:
    data = await _fetch_wc26(f"/get/group/{group_id}", f"wc26:group:{group_id}", CACHE_TTLS["wc26:group:"])
    if not data:
        return None

    # Enriquecer nombres de equipos en el grupo
    teams_data = await get_wc_teams()
    teams_map = {}
    if teams_data:
        for t in teams_data.get("teams", []):
            teams_map[t.get("id", "")] = t

    group = data.get("group", data)
    if group and "teams" in group:
        enriched_teams = []
        for team_entry in group["teams"]:
            team_id = team_entry.get("team_id", "")
            team_info = teams_map.get(team_id, {})
            enriched_teams.append({
                **team_entry,
                "name_en": team_info.get("name_en", ""),
                "name_es": team_info.get("name_es", _map_team(team_info.get("name_en", ""))),
                "flag": team_info.get("flag", ""),
                "fifa_code": team_info.get("fifa_code", ""),
            })
        group["teams"] = enriched_teams

    return data


# ============================================================================
# PARTIDOS (con nombres en español + hora CDMX)
# ============================================================================

async def get_wc_games() -> Optional[Dict]:
    data = await _fetch_wc26("/get/games", "wc26:games", CACHE_TTLS["wc26:games"])
    if not data or "games" not in data:
        return None

    # Precargar equipos y estadios
    teams_data = await get_wc_teams()
    teams_map = {}
    if teams_data:
        for t in teams_data.get("teams", []):
            teams_map[t.get("id", "")] = t

    stadiums_data = await get_wc_stadiums()
    stadiums_map = {}
    if stadiums_data:
        for s in stadiums_data.get("stadiums", []):
            stadiums_map[s.get("id", "")] = s

    enriched_games = []
    for game in data["games"]:
        home_id = game.get("home_team_id", "")
        away_id = game.get("away_team_id", "")
        stadium_id = game.get("stadium_id", "")

        home_info = teams_map.get(home_id, {})
        away_info = teams_map.get(away_id, {})
        stadium_info = stadiums_map.get(stadium_id, {})

        # Nombres en español
        home_name_en = game.get("home_team_name_en") or home_info.get("name_en", "")
        away_name_en = game.get("away_team_name_en") or away_info.get("name_en", "")
        home_name_es = _map_team(home_name_en) if home_name_en else game.get("home_team_label", "TBD")
        away_name_es = _map_team(away_name_en) if away_name_en else game.get("away_team_label", "TBD")

        # Horario CDMX
        local_date = game.get("local_date", "")
        time_info = _convert_to_cdmx(local_date, stadium_id)

        # Estado
        status = _determine_status(game)

        # Goleadores parseados
        home_scorers = _parse_scorers(game.get("home_scorers", ""))
        away_scorers = _parse_scorers(game.get("away_scorers", ""))

        enriched_games.append({
            **game,
            "home_team_name_es": home_name_es,
            "away_team_name_es": away_name_es,
            "home_team_name_original": home_name_en,
            "away_team_name_original": away_name_en,
            "home_flag": home_info.get("flag", ""),
            "away_flag": away_info.get("flag", ""),
            "home_fifa_code": home_info.get("fifa_code", ""),
            "away_fifa_code": away_info.get("fifa_code", ""),
            "home_group": home_info.get("groups", ""),
            "away_group": away_info.get("groups", ""),
            "stadium_name_en": stadium_info.get("name_en", ""),
            "stadium_name_es": stadium_info.get("name_en", ""),  # Se puede traducir si se desea
            "stadium_city": stadium_info.get("city_en", ""),
            "stadium_country": stadium_info.get("country_en", ""),
            "stadium_capacity": stadium_info.get("capacity"),
            "stadium_region": stadium_info.get("region", ""),
            "date_iso": time_info["date_iso"],
            "time_local": time_info["time_local"],
            "time_cdmx": time_info["time_cdmx"],
            "datetime_iso": time_info["datetime_iso"],
            "datetime_cdmx_iso": time_info["datetime_cdmx_iso"],
            "timezone_local": time_info["timezone_local"],
            "timezone_cdmx": time_info["timezone_cdmx"],
            "status": status,
            "home_scorers_list": home_scorers,
            "away_scorers_list": away_scorers,
        })

    return {"games": enriched_games, "count": len(enriched_games)}

async def get_wc_game(game_id: str) -> Optional[Dict]:
    data = await _fetch_wc26(f"/get/game/{game_id}", f"wc26:game:{game_id}", CACHE_TTLS["wc26:game:"])
    if not data:
        return None

    # Enriquecer un solo partido (misma lógica que get_wc_games pero para uno)
    game = data.get("game", data)
    if not game:
        return data

    teams_data = await get_wc_teams()
    teams_map = {}
    if teams_data:
        for t in teams_data.get("teams", []):
            teams_map[t.get("id", "")] = t

    stadiums_data = await get_wc_stadiums()
    stadiums_map = {}
    if stadiums_data:
        for s in stadiums_data.get("stadiums", []):
            stadiums_map[s.get("id", "")] = s

    home_id = game.get("home_team_id", "")
    away_id = game.get("away_team_id", "")
    stadium_id = game.get("stadium_id", "")

    home_info = teams_map.get(home_id, {})
    away_info = teams_map.get(away_id, {})
    stadium_info = stadiums_map.get(stadium_id, {})

    home_name_en = game.get("home_team_name_en") or home_info.get("name_en", "")
    away_name_en = game.get("away_team_name_en") or away_info.get("name_en", "")
    home_name_es = _map_team(home_name_en) if home_name_en else game.get("home_team_label", "TBD")
    away_name_es = _map_team(away_name_en) if away_name_en else game.get("away_team_label", "TBD")

    local_date = game.get("local_date", "")
    time_info = _convert_to_cdmx(local_date, stadium_id)
    status = _determine_status(game)

    game.update({
        "home_team_name_es": home_name_es,
        "away_team_name_es": away_name_es,
        "home_team_name_original": home_name_en,
        "away_team_name_original": away_name_en,
        "home_flag": home_info.get("flag", ""),
        "away_flag": away_info.get("flag", ""),
        "home_fifa_code": home_info.get("fifa_code", ""),
        "away_fifa_code": away_info.get("fifa_code", ""),
        "home_group": home_info.get("groups", ""),
        "away_group": away_info.get("groups", ""),
        "stadium_name_en": stadium_info.get("name_en", ""),
        "stadium_city": stadium_info.get("city_en", ""),
        "stadium_country": stadium_info.get("country_en", ""),
        "stadium_capacity": stadium_info.get("capacity"),
        "stadium_region": stadium_info.get("region", ""),
        "date_iso": time_info["date_iso"],
        "time_local": time_info["time_local"],
        "time_cdmx": time_info["time_cdmx"],
        "datetime_iso": time_info["datetime_iso"],
        "datetime_cdmx_iso": time_info["datetime_cdmx_iso"],
        "timezone_local": time_info["timezone_local"],
        "timezone_cdmx": time_info["timezone_cdmx"],
        "status": status,
        "home_scorers_list": _parse_scorers(game.get("home_scorers", "")),
        "away_scorers_list": _parse_scorers(game.get("away_scorers", "")),
    })

    return data


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
