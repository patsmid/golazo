import httpx
import datetime
from typing import List, Dict
from urllib.parse import quote
from zoneinfo import ZoneInfo

API_BASE = "https://worldcup26.ir"

TEAM_NAME_MAP = {
    "Australia": "Australia",
    "Turkey": "Turquía",
    "Qatar": "Catar",
    "Switzerland": "Suiza",
    "United States": "Estados Unidos",
    "Germany": "Alemania",
    "Ivory Coast": "Costa de Marfil",
    "Netherlands": "Países Bajos",
    "Sweden": "Suecia",
    "France": "Francia",
    "Iraq": "Irak",
    "Norway": "Noruega",
    "Senegal": "Senegal",
    "Japan": "Japón",
    "Tunisia": "Túnez",
    "Haiti": "Haití",
    "Scotland": "Escocia",
    "England": "Inglaterra",
    "Croatia": "Croacia",
    "Spain": "España",
    "Saudi Arabia": "Arabia Saudita",
    "Jordan": "Jordania",
    "Algeria": "Argelia",
    "Portugal": "Portugal",
    "Uzbekistan": "Uzbekistán",
    "Panama": "Panamá",
    "Czech Republic": "República Checa",
    "Mexico": "México",
    "South Korea": "Corea del Sur",
    "Paraguay": "Paraguay",
    "Morocco": "Marruecos",
    "Brazil": "Brasil",
    "Canada": "Canadá",
    "Bosnia and Herzegovina": "Bosnia y Herzegovina",
    "Belgium": "Bélgica",
    "Iran": "Irán",
    "Egypt": "Egipto",
    "New Zealand": "Nueva Zelanda",
    "Cape Verde": "Cabo Verde",
    "Uruguay": "Uruguay",
    "Austria": "Austria",
    "Argentina": "Argentina",
    "Colombia": "Colombia",
    "Democratic Republic of the Congo": "Rep. Dem. del Congo",
    "Ecuador": "Ecuador",
    "Curaçao": "Curazao",
    "South Africa": "Sudáfrica",
    "Ghana": "Ghana",
    "Italia": "Italia",
    "Polonia": "Polonia",
    "Serbia": "Serbia",
    "Dinamarca": "Dinamarca",
    "Perú": "Perú",
    "Chile": "Chile",
    "Camerún": "Camerún",
    "Nigeria": "Nigeria",
    "Costa Rica": "Costa Rica",
}

STADIUM_TIMEZONES = {
    "1": "America/Mexico_City",
    "2": "America/Mexico_City",
    "3": "America/Mexico_City",
    "4": "America/Chicago",
    "5": "America/Chicago",
    "6": "America/Chicago",
    "7": "America/New_York",
    "8": "America/New_York",
    "9": "America/New_York",
    "10": "America/New_York",
    "11": "America/New_York",
    "12": "America/Toronto",
    "13": "America/Vancouver",
    "14": "America/Los_Angeles",
    "15": "America/Los_Angeles",
    "16": "America/Los_Angeles",
}

_teams_cache: Dict[str, dict] = {}
_stadiums_cache: Dict[str, dict] = {}

def _map_team(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name)

async def _load_teams():
    global _teams_cache
    if _teams_cache:
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(f"{API_BASE}/get/teams")
            resp.raise_for_status()
            data = resp.json()
            for t in data.get("teams", []):
                _teams_cache[t.get("id", "")] = t
            print(f"✅ Cargados {len(_teams_cache)} equipos desde worldcup26.ir")
        except Exception as e:
            print(f"Error cargando teams: {e}")

async def _load_stadiums():
    global _stadiums_cache
    if _stadiums_cache:
        return
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(f"{API_BASE}/get/stadiums")
            resp.raise_for_status()
            data = resp.json()
            for s in data.get("stadiums", []):
                _stadiums_cache[s.get("id", "")] = s
            print(f"✅ Cargados {len(_stadiums_cache)} estadios desde worldcup26.ir")
        except Exception as e:
            print(f"Error cargando stadiums: {e}")

async def get_teams() -> List[Dict]:
    await _load_teams()
    return list(_teams_cache.values())

async def get_stadiums() -> List[Dict]:
    await _load_stadiums()
    return list(_stadiums_cache.values())

async def fetch_upcoming_matches() -> List[Dict]:
    """Obtiene los próximos partidos (no empezados) desde worldcup26.ir."""
    await _load_teams()
    await _load_stadiums()

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(f"{API_BASE}/get/games")
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"Error worldcup26.ir: {e}")
            return []

    matches = []
    today = datetime.date.today()
    mexico_tz = ZoneInfo("America/Mexico_City")

    for game in data.get("games", []):
        # Solo partidos no empezados (time_elapsed == "notstarted" o vacío)
        time_elapsed = game.get("time_elapsed", "")
        if time_elapsed != "notstarted":
            continue  # No son futuros
        if game.get("home_team_id") == "0" or game.get("away_team_id") == "0":
            continue

        local_date = game.get("local_date", "")
        try:
            dt = datetime.datetime.strptime(local_date, "%m/%d/%Y %H:%M")
            match_date = dt.date()
        except Exception:
            continue

        if match_date < today:
            continue

        home_id = game.get("home_team_id", "")
        away_id = game.get("away_team_id", "")
        home_data = _teams_cache.get(home_id, {})
        away_data = _teams_cache.get(away_id, {})

        home = _map_team(home_data.get("name_en", game.get("home_team_name_en", "")))
        away = _map_team(away_data.get("name_en", game.get("away_team_name_en", "")))

        stadium_id = game.get("stadium_id", "")
        stadium_info = _stadiums_cache.get(stadium_id, {})
        venue_name = stadium_info.get("name_en", "Por determinar")
        city = stadium_info.get("city_en", "")
        country = stadium_info.get("country_en", "")
        capacity = stadium_info.get("capacity")

        stadium_tz_str = STADIUM_TIMEZONES.get(stadium_id, "America/Mexico_City")
        stadium_tz = ZoneInfo(stadium_tz_str)
        dt_with_tz = dt.replace(tzinfo=stadium_tz)
        dt_mx = dt_with_tz.astimezone(mexico_tz)
        datetimeMX = dt_mx.isoformat()

        matches.append({
            "match_id": str(game.get("id")),
            "home_team": home,
            "away_team": away,
            "home_flag": home_data.get("flag"),
            "away_flag": away_data.get("flag"),
            "home_fifa_code": home_data.get("fifa_code"),
            "away_fifa_code": away_data.get("fifa_code"),
            "home_group": home_data.get("groups"),
            "away_group": away_data.get("groups"),
            "date": match_date.isoformat(),
            "datetime": dt.isoformat(),
            "datetimeMX": datetimeMX,
            "venue": venue_name,
            "city": city,
            "country": country,
            "capacity": capacity,
            "group": game.get("group", ""),
            "stage": game.get("stage", ""),
        })

    # En fetch_upcoming_matches, al final:
    matches.sort(key=lambda x: x["date"])
    print(f"worldcup26.ir: {len(matches)} próximos partidos")
    return matches  # <--- quitamos [:10]

async def fetch_recent_results() -> List[Dict]:
    await _load_teams()
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(f"{API_BASE}/get/games")
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"Error worldcup26.ir: {e}")
            return []

    results = []
    today = datetime.date.today()
    for game in data.get("games", []):
        if game.get("finished") != "TRUE":
            continue
        if game.get("home_team_id") == "0" or game.get("away_team_id") == "0":
            continue
        local_date = game.get("local_date", "")
        try:
            dt = datetime.datetime.strptime(local_date, "%m/%d/%Y %H:%M")
            match_date = dt.date()
        except Exception:
            continue
        if (today - match_date).days > 3:
            continue
        home_id = game.get("home_team_id", "")
        away_id = game.get("away_team_id", "")
        home_data = _teams_cache.get(home_id, {})
        away_data = _teams_cache.get(away_id, {})
        home = _map_team(home_data.get("name_en", game.get("home_team_name_en", "")))
        away = _map_team(away_data.get("name_en", game.get("away_team_name_en", "")))
        home_goals = int(game.get("home_score", 0))
        away_goals = int(game.get("away_score", 0))
        results.append({
            "home_team": home,
            "away_team": away,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "home_flag": home_data.get("flag"),
            "away_flag": away_data.get("flag"),
            "home_fifa_code": home_data.get("fifa_code"),
            "away_fifa_code": away_data.get("fifa_code"),
            "date": match_date.isoformat(),
            "group": game.get("group", ""),
        })
    print(f"worldcup26.ir: {len(results)} resultados recientes")
    return results

async def fetch_all_matches() -> List[Dict]:
    await _load_teams()
    await _load_stadiums()
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(f"{API_BASE}/get/games")
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"Error worldcup26.ir: {e}")
            return []

    matches = []
    mexico_tz = ZoneInfo("America/Mexico_City")
    for game in data.get("games", []):
        if game.get("home_team_id") == "0" or game.get("away_team_id") == "0":
            continue
        local_date = game.get("local_date", "")
        try:
            dt = datetime.datetime.strptime(local_date, "%m/%d/%Y %H:%M")
            match_date = dt.date()
        except Exception:
            continue
        home_id = game.get("home_team_id", "")
        away_id = game.get("away_team_id", "")
        home_data = _teams_cache.get(home_id, {})
        away_data = _teams_cache.get(away_id, {})
        home = _map_team(home_data.get("name_en", game.get("home_team_name_en", "")))
        away = _map_team(away_data.get("name_en", game.get("away_team_name_en", "")))

        stadium_id = game.get("stadium_id", "")
        stadium_info = _stadiums_cache.get(stadium_id, {})
        venue_name = stadium_info.get("name_en", "Por determinar")
        city = stadium_info.get("city_en", "")
        country = stadium_info.get("country_en", "")
        capacity = stadium_info.get("capacity")

        stadium_tz_str = STADIUM_TIMEZONES.get(stadium_id, "America/Mexico_City")
        stadium_tz = ZoneInfo(stadium_tz_str)
        dt_with_tz = dt.replace(tzinfo=stadium_tz)
        dt_mx = dt_with_tz.astimezone(mexico_tz)
        datetimeMX = dt_mx.isoformat()

        finished = game.get("finished") == "TRUE"
        time_elapsed = game.get("time_elapsed", "notstarted")
        status = "finished" if finished else ("live" if time_elapsed != "notstarted" else "upcoming")
        home_goals = int(game.get("home_score", 0)) if finished else None
        away_goals = int(game.get("away_score", 0)) if finished else None

        matches.append({
            "match_id": str(game.get("id")),
            "home_team": home,
            "away_team": away,
            "home_flag": home_data.get("flag"),
            "away_flag": away_data.get("flag"),
            "home_fifa_code": home_data.get("fifa_code"),
            "away_fifa_code": away_data.get("fifa_code"),
            "home_group": home_data.get("groups"),
            "away_group": away_data.get("groups"),
            "date": match_date.isoformat(),
            "datetime": dt.isoformat(),
            "datetimeMX": datetimeMX,
            "venue": venue_name,
            "city": city,
            "country": country,
            "capacity": capacity,
            "group": game.get("group", ""),
            "stage": game.get("stage", ""),
            "status": status,
            "home_score": home_goals,
            "away_score": away_goals,
        })
    matches.sort(key=lambda x: int(x["match_id"]))
    return matches
