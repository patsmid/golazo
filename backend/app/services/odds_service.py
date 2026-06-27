# =============================================================================
# odds_service.py  —  MULTI-PROVEEDOR CON CACHÉ AGRESIVO
# =============================================================================
# CAMBIOS RESPECTO A LA VERSIÓN ANTERIOR:
#   1. Ya NO hace 1 llamada API por partido.
#   2. Hace 1 sola llamada para traer TODAS las odds del Mundial y las cachea.
#   3. Proveedores en orden: OddsPapi (gratis, 350+ books) → The Odds API (fallback).
#   4. Si ambas fallan, usa la última caché válida (datos algo antiguos > sin datos).
#   5. La interfaz pública (get_enriched_odds) NO CAMBIA: prediction_service.py
#      sigue funcionando igual sin modificaciones.
#
# CONFIGURACIÓN REQUERIDA en app/config.py:
#   ODDS_PAPI_API_KEY = "tu-key-gratis-de-oddspapi.io"   # ← NUEVA, obligatoria
#   ODDS_API_KEY      = "tu-key-de-the-odds-api"         # ← Existente, ahora fallback
# =============================================================================

import httpx
import os
import time
import difflib
import json
from typing import List, Dict, Optional, Any
from app.config import ODDS_API_KEY

# ── Nuevas configuraciones ──────────────────────────────────────────────────
try:
    from app.config import ODDS_PAPI_API_KEY
except ImportError:
    ODDS_PAPI_API_KEY = os.getenv("ODDS_PAPI_KEY", "")

try:
    from app.cache.redis_client import cache_get, cache_set, redis_client
except ImportError:
    redis_client = None
    cache_get = None
    cache_set = None

# ── Constantes ──────────────────────────────────────────────────────────────
CACHE_KEY_ALL_ODDS = "wc2026:all_odds_cache"
CACHE_KEY_ALL_ODDS_META = "wc2026:all_odds_meta"
CACHE_TTL_ODDS = 8 * 3600          # 8 horas de caché (ajustable)
STALE_TTL_ODDS = 48 * 3600         # Si el proveedor falla, aceptar caché de hasta 48h

# The Odds API
TOA_BASE = "https://api.the-odds-api.com/v4"
TOA_SPORT = "soccer_fifa_world_cup"
TOA_REGIONS = "us,uk,eu"
TOA_MARKETS = "h2h"

# OddsPapi
PAPI_BASE = "https://api.oddspapi.io/v4"
PAPI_SOCCER_SPORT_ID = 10           # Fijo según su documentación

# Bookmakers prioritarios (se usan igual para ambos proveedores)
PRIORITY_BOOKMAKERS = [
    "pinnacle", "bet365", "fanduel", "draftkings", "betmgm",
    "caesars", "williamhill", "unibet", "1xbet", "betfair"
]

# Sinónimos para normalizar nombres
TEAM_SYNONYMS = {
    "Rep. Dem. del Congo": "Congo DR",
    "Congo": "Congo DR",
    "RD Congo": "Congo DR",
    "DR Congo": "Congo DR",
    "Estados Unidos": "USA",
    "United States": "USA",
    "US": "USA",
    "Corea del Sur": "South Korea",
    "South Korea": "South Korea",
    "Korea Republic": "South Korea",
    "Korea": "South Korea",
    "Países Bajos": "Netherlands",
    "Holanda": "Netherlands",
    "República Checa": "Czech Republic",
    "Czechia": "Czech Republic",
    "Costa de Marfil": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Arabia Saudita": "Saudi Arabia",
    "Saudi": "Saudi Arabia",
    "Nueva Zelanda": "New Zealand",
    "Cabo Verde": "Cape Verde",
    "Bosnia y Herzegovina": "Bosnia and Herzegovina",
    "Bosnia": "Bosnia and Herzegovina",
    "Inglaterra": "England",
    "Irán": "Iran",
    "Turquía": "Turkey",
    "Japón": "Japan",
    "Marruecos": "Morocco",
    "Brasil": "Brazil",
    "Argentina": "Argentina",
    "Francia": "France",
    "Alemania": "Germany",
    "España": "Spain",
    "Portugal": "Portugal",
    "Uruguay": "Uruguay",
    "Colombia": "Colombia",
    "México": "Mexico",
    "Ecuador": "Ecuador",
    "Perú": "Peru",
    "Chile": "Chile",
    "Paraguay": "Paraguay",
    "Túnez": "Tunisia",
    "Egipto": "Egypt",
    "Senegal": "Senegal",
    "Camerún": "Cameroon",
    "Cameroon": "Cameroon",
    "Ghana": "Ghana",
    "Nigeria": "Nigeria",
    "Costa Rica": "Costa Rica",
    "Panamá": "Panama",
    "Panama": "Panama",
    "Canadá": "Canada",
    "Haití": "Haiti",
    "Haiti": "Haiti",
    "Curazao": "Curaçao",
    "Curaçao": "Curaçao",
    "Curaçao": "Curacao",
    "Curacao": "Curaçao",
    "Escocia": "Scotland",
    "Suecia": "Sweden",
    "Noruega": "Norway",
    "Bélgica": "Belgium",
    "Austria": "Austria",
    "Croacia": "Croatia",
    "Suiza": "Switzerland",
    "Serbia": "Serbia",
    "Dinamarca": "Denmark",
    "Polonia": "Poland",
    "Ucrania": "Ukraine",
    "Rumanía": "Romania",
    "Rusia": "Russia",
    "Turquía": "Turkey",
    "Eslovaquia": "Slovakia",
    "Eslovenia": "Slovenia",
    "Australia": "Australia",
    "China": "China",
    "Emiratos Árabes": "UAE",
    "UAE": "UAE",
    "Irak": "Iraq",
    "Iraq": "Iraq",
    "Jordania": "Jordan",
    "Argelia": "Algeria",
    "Algeria": "Algeria",
    "Sudáfrica": "South Africa",
    "South Africa": "South Africa",
    "Qatar": "Qatar",
    "Catar": "Qatar",
    "Uzbekistán": "Uzbekistan",
    "Uzbekistan": "Uzbekistan",
}

# =============================================================================
# UTILIDADES DE NORMALIZACIÓN (sin cambios funcionales)
# =============================================================================

def normalize(name: str) -> str:
    """Normaliza y mapea nombres para comparación."""
    import unicodedata
    if not name:
        return ""
    name = name.strip().lower()
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    # Reemplazar guiones y paréntesis por espacios
    name = name.replace("-", " ").replace("(", " ").replace(")", " ")
    # Buscar sinónimo exacto primero
    for our, api in TEAM_SYNONYMS.items():
        if normalize_raw(our) == name:
            return normalize_raw(api)
    return name

def normalize_raw(name: str) -> str:
    import unicodedata
    name = name.strip().lower()
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    return name.replace("-", " ").replace("(", " ").replace(")", " ")

def fuzzy_match(event_teams: List[str], search: str, threshold=0.75) -> Optional[str]:
    """Busca coincidencia difusa entre una lista de nombres y el buscado."""
    search_n = normalize(search)
    best = None
    best_ratio = 0
    for t in event_teams:
        t_n = normalize(t)
        ratio = difflib.SequenceMatcher(None, search_n, t_n).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = t
    return best if best_ratio >= threshold else None


# =============================================================================
# CAPA DE CACHÉ (Redis o en memoria)
# =============================================================================

_in_memory_cache: Dict[str, Any] = {}
_in_memory_meta: Dict[str, Any] = {}

def _cache_get(key: str) -> Optional[Any]:
    """Obtiene del caché (Redis primero, luego memoria)."""
    global _in_memory_cache, _in_memory_meta
    if key == CACHE_KEY_ALL_ODDS_META:
        if _in_memory_meta:
            return _in_memory_meta
    if key == CACHE_KEY_ALL_ODDS:
        if _in_memory_cache:
            return _in_memory_cache

    if cache_get and redis_client:
        try:
            raw = cache_get(key)
            if raw:
                if isinstance(raw, str):
                    return json.loads(raw)
                return raw
        except Exception:
            pass

    if key == CACHE_KEY_ALL_ODDS:
        return _in_memory_cache if _in_memory_cache else None
    if key == CACHE_KEY_ALL_ODDS_META:
        return _in_memory_meta if _in_memory_meta else None
    return None

def _cache_set(key: str, value: Any, ttl: int):
    """Guarda en caché (Redis y memoria)."""
    global _in_memory_cache, _in_memory_meta
    if key == CACHE_KEY_ALL_ODDS:
        _in_memory_cache = value
    elif key == CACHE_KEY_ALL_ODDS_META:
        _in_memory_meta = value

    if cache_set and redis_client:
        try:
            to_store = json.dumps(value) if isinstance(value, (dict, list)) else value
            cache_set(key, to_store, ttl)
        except Exception:
            pass

def get_cached_events() -> Optional[List[Dict]]:
    """Obtiene eventos del caché (acepta caché stale si no hay fresco)."""
    # Intentar caché fresco
    meta = _cache_get(CACHE_KEY_ALL_ODDS_META)
    if meta and meta.get("events"):
        age = time.time() - meta.get("timestamp", 0)
        if age < CACHE_TTL_ODDS:
            return meta["events"]
        if age < STALE_TTL_ODDS:
            # Caché antiguo pero usable — lo marcamos
            meta["_stale"] = True
            return meta["events"]
    return None

def set_cached_events(events: List[Dict], provider: str):
    """Guarda eventos en caché con metadatos."""
    _cache_set(CACHE_KEY_ALL_ODDS, events, CACHE_TTL_ODDS)
    _cache_set(CACHE_KEY_ALL_ODDS_META, {
        "timestamp": time.time(),
        "provider": provider,
        "count": len(events),
        "events": events,
    }, CACHE_TTL_ODDS)

# =============================================================================
# PROVEEDOR 1: ODDS PAPI  (GRATIS — 350+ bookmakers)
# =============================================================================
# /fixtures = solo horarios (bookmakers=None, hasOdds=False)
# /odds = datos reales de cuotas
# Estrategia: 1 llamada a /fixtures para obtener tournamentId (cacheado 7 dias)
#             1 llamada a /odds con ese tournamentId
# Total: 2 creditos la primera vez, 1 credito despues = ~180/mes
# =============================================================================

# Ventanas de 10 dias para el Mundial 2026 (jun 11 - jul 19)
WC2026_DATE_WINDOWS = [
    ("2026-06-11", "2026-06-20"),
    ("2026-06-21", "2026-06-30"),
    ("2026-07-01", "2026-07-10"),
    ("2026-07-11", "2026-07-19"),
]

_papi_last_call = 0.0
_papi_odds_debug_done = False


def _papi_extract_outcomes(bk: Dict, home: str, away: str) -> List[Dict]:
    """Extrae outcomes home/draw/away de un bookmaker OddsPapi."""
    outcomes = []
    odds_dict = bk.get("odds", {})
    if isinstance(odds_dict, dict):
        for market_key in ["matchWinner", "h2h", "moneyline", "1x2", "match_winner", "winner"]:
            if market_key in odds_dict:
                market = odds_dict[market_key]
                if isinstance(market, dict):
                    h = market.get("home") or market.get("1")
                    d = market.get("draw") or market.get("x") or market.get("X")
                    a = market.get("away") or market.get("2")
                    if h:
                        outcomes.append({"name": home, "price": float(h)})
                    if d:
                        outcomes.append({"name": "Draw", "price": float(d)})
                    if a:
                        outcomes.append({"name": away, "price": float(a)})
                    if outcomes:
                        return outcomes
    markets = bk.get("markets", [])
    if isinstance(markets, list):
        for m in markets:
            if not isinstance(m, dict):
                continue
            mkey = str(m.get("key", "") or m.get("name", "")).lower()
            if mkey not in ["matchwinner", "h2h", "moneyline", "1x2", "match_winner", "winner"]:
                continue
            for o in m.get("outcomes", []):
                if not isinstance(o, dict):
                    continue
                o_name = str(o.get("name", "") or o.get("outcome", "") or o.get("label", ""))
                o_price = o.get("price") or o.get("odds") or o.get("value")
                if o_name and o_price:
                    nl = o_name.lower()
                    if nl in ["home", "1", "local"]:
                        o_name = home
                    elif nl in ["away", "2", "visitante"]:
                        o_name = away
                    elif nl in ["draw", "tie", "x", "empate"]:
                        o_name = "Draw"
                    outcomes.append({"name": o_name, "price": float(o_price)})
            if outcomes:
                return outcomes
    return outcomes


def _normalize_papi_fixture(fixture: Dict) -> Optional[Dict]:
    """Convierte fixture/odd de OddsPapi a formato interno."""
    try:
        home = (fixture.get("participant1Name") or fixture.get("homeTeam") or
                fixture.get("home_team") or fixture.get("homeName") or
                fixture.get("home", ""))
        away = (fixture.get("participant2Name") or fixture.get("awayTeam") or
                fixture.get("away_team") or fixture.get("awayName") or
                fixture.get("away", ""))
        if not home or not away:
            return None

        event_id = str(fixture.get("id", "") or fixture.get("fixtureId", ""))
        raw_bks = fixture.get("bookmakers", [])
        normalized_bks = []

        for bk in raw_bks:
            if not isinstance(bk, dict):
                continue
            bk_key = str(bk.get("id", "") or bk.get("key", "") or "").lower()
            bk_title = bk.get("name", "") or bk.get("bookmakerName", "") or bk_key
            if not bk_key:
                continue
            bk_outcomes = _papi_extract_outcomes(bk, home, away)
            if not bk_outcomes:
                continue
            normalized_bks.append({
                "key": bk_key,
                "title": bk_title,
                "last_update": str(fixture.get("lastUpdate", fixture.get("updatedAt", ""))),
                "markets": [{"key": "h2h", "outcomes": bk_outcomes}]
            })

        if not normalized_bks:
            return None

        return {
            "id": event_id,
            "home_team": home,
            "away_team": away,
            "bookmakers": normalized_bks,
            "_provider": "oddspapi"
        }
    except Exception as e:
        print(f"⚠️ Error normalizando: {e}")
        return None


async def _papi_fetch_all_odds() -> Optional[List[Dict]]:
    """Obtiene odds WC: /fixtures para tournamentId, luego /odds."""
    global _papi_last_call, _papi_odds_debug_done

    if not ODDS_PAPI_API_KEY:
        return None

    # Rate limit: 1 intento cada 10 minutos
    now = time.time()
    wait = 600 - (now - _papi_last_call)
    if wait > 0:
        print(f"⏳ OddsPapi: Esperando {int(wait)}s")
        return None
    _papi_last_call = now

    headers = {"User-Agent": "GolazoWorldCup/1.0", "Accept": "application/json"}

    # ── PASO 1: Obtener tournamentId (cacheado 7 dias) ──
    tid_key = "wc2026:papi_wc_tid"
    wc_tid = _cache_get(tid_key)

    if not wc_tid:
        print("📌 OddsPapi: Obteniendo tournamentId...")
        try:
            async with httpx.AsyncClient(timeout=20, headers=headers) as client:
                resp = await client.get(f"{PAPI_BASE}/fixtures", params={
                    "apiKey": ODDS_PAPI_API_KEY,
                    "sportId": PAPI_SOCCER_SPORT_ID,
                    "from": "2026-07-11",
                    "to": "2026-07-19",
                })
                if resp.status_code != 200:
                    print(f"⚠️ OddsPapi fixtures: HTTP {resp.status_code}")
                    return None
                for f in resp.json():
                    if isinstance(f, dict) and f.get("tournamentName") == "World Cup" and f.get("tournamentId"):
                        wc_tid = str(f["tournamentId"])
                        break
                if wc_tid:
                    _cache_set(tid_key, wc_tid, 7 * 24 * 3600)
                    print(f"✅ WC tournamentId = {wc_tid} (cacheado)")
                else:
                    print("⚠️ No se encontro World Cup en fixtures")
                    return None
        except Exception as e:
            print(f"❌ OddsPapi paso 1: {e}")
            return None

    # ── PASO 2: Obtener odds del endpoint /odds ──
    print(f"🔍 OddsPapi: Obteniendo odds (tid={wc_tid})...")
    try:
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            resp = await client.get(f"{PAPI_BASE}/odds", params={
                "apiKey": ODDS_PAPI_API_KEY,
                "sportId": PAPI_SOCCER_SPORT_ID,
                "tournamentId": wc_tid,
            })

            if resp.status_code == 429:
                print("⚠️ OddsPapi /odds: 429")
                return None
            if resp.status_code != 200:
                print(f"⚠️ OddsPapi /odds: HTTP {resp.status_code} — {resp.text[:300]}")
                return None

            data = resp.json()

            # Extraer lista de items
            if isinstance(data, dict):
                items = (data.get("data") or data.get("odds") or
                         data.get("fixtures") or data.get("events") or
                         data.get("matches") or [])
            elif isinstance(data, list):
                items = data
            else:
                print(f"⚠️ OddsPapi /odds: formato {type(data)}")
                return None

            if not items:
                print("⚠️ OddsPapi /odds: respuesta vacia")
                return None

            # ── DIAGNOSTICO UNA SOLA VEZ ──
            if not _papi_odds_debug_done:
                _papi_odds_debug_done = True
                first = items[0]
                if isinstance(first, dict):
                    print(f"🔍 /odds claves: {list(first.keys())}")
                    # Buscar donde estan las odds
                    for bk_key in ["bookmakers", "books", "odds", "markets", "prices"]:
                        if bk_key in first:
                            val = first[bk_key]
                            print(f"   '{bk_key}': tipo={type(val).__name__}")
                            if isinstance(val, list) and val and isinstance(val[0], dict):
                                print(f"   [0] claves: {list(val[0].keys())}")
                                b0 = val[0]
                                for ok in ["odds", "markets", "outcomes", "prices"]:
                                    if ok in b0:
                                        print(f"   [0].{ok} = {str(b0[ok])[:400]}")
                            elif isinstance(val, dict):
                                print(f"   claves: {list(val.keys())}")
                                for ok in val:
                                    print(f"   {ok} = {str(val[ok])[:200]}")
                            break
                    else:
                        print(f"   ⚠️ Sin bookmakers/odds/markets")
                        s = str(first)
                        if len(s) < 600:
                            print(f"   Completo: {s}")
            # ── FIN DIAGNOSTICO ──

            # Normalizar
            normalized = []
            for item in items:
                evt = _normalize_papi_fixture(item)
                if evt:
                    normalized.append(evt)

            if normalized:
                print(f"✅ OddsPapi: {len(normalized)} partidos con odds")
                return normalized
            else:
                print(f"⚠️ OddsPapi: {len(items)} items, 0 normalizados (ver diagnostico)")
                return None

    except Exception as e:
        print(f"❌ OddsPapi /odds: {e}")
        return None

# =============================================================================
# PROVEEDOR 2: THE ODDS API  (FALLBACK — tu proveedor actual)
# =============================================================================

async def _toa_fetch_all_odds() -> Optional[List[Dict]]:
    """
    Obtiene TODAS las odds del Mundial desde The Odds API (tu proveedor actual).
    Retorna lista en formato nativo de The Odds API.
    """
    if not ODDS_API_KEY:
        return None

    try:
        url = f"{TOA_BASE}/sports/{TOA_SPORT}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": TOA_REGIONS,
            "markets": TOA_MARKETS,
            "oddsFormat": "decimal"
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)

            if resp.status_code == 429:
                print("⚠️ The Odds API: Rate limit (429). Créditos agotados.")
                return None
            resp.raise_for_status()
            events = resp.json()

            if not events:
                print("⚠️ The Odds API: No hay eventos para soccer_fifa_world_cup.")
                return None

            # Marcar cada evento con el proveedor
            for evt in events:
                evt["_provider"] = "the_odds_api"

            print(f"✅ The Odds API: {len(events)} partidos obtenidos")
            return events

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            print("⚠️ The Odds API: Rate limit (429). Créditos agotados.")
        else:
            print(f"⚠️ The Odds API HTTP error: {e.response.status_code}")
        return None
    except Exception as e:
        print(f"❌ The Odds API fetch error: {e}")
        return None


# =============================================================================
# ORQUESTRADOR: OBTENER TODAS LAS ODDS (con cadena de fallback)
# =============================================================================

async def fetch_all_odds(force_refresh: bool = False) -> List[Dict]:
    """
    ORQUESTRADOR PRINCIPAL.

    Estrategia:
      1. Si hay caché fresco (< 4h) y no es force_refresh → usar caché
      2. Intentar OddsPapi (gratis, 350+ books)
      3. Si falla → intentar The Odds API
      4. Si ambos fallan → usar caché stale (< 48h) si existe
      5. Si no hay nada → retornar lista vacía

    Retorna: Lista de eventos en formato normalizado.
    """
    # 1. Caché fresco
    if not force_refresh:
        meta = _cache_get(CACHE_KEY_ALL_ODDS_META)
        if meta and meta.get("events"):
            age = time.time() - meta.get("timestamp", 0)
            if age < CACHE_TTL_ODDS:
                stale = meta.get("_stale", False)
                if not stale:
                    provider = meta.get("provider", "cache")
                    count = len(meta["events"])
                    print(f"📦 Caché fresco ({provider}): {count} partidos (edad: {int(age/60)}min)")
                    return meta["events"]

    # 2. Intentar OddsPapi
    print("🔍 Intentando OddsPapi...")
    papi_events = await _papi_fetch_all_odds()
    if papi_events and len(papi_events) > 0:
        set_cached_events(papi_events, "oddspapi")
        return papi_events

    # 3. Intentar The Odds API
    print("🔍 OddsPapi sin datos. Intentando The Odds API...")
    toa_events = await _toa_fetch_all_odds()
    if toa_events and len(toa_events) > 0:
        set_cached_events(toa_events, "the_odds_api")
        return toa_events

    # 4. Caché stale como último recurso
    meta = _cache_get(CACHE_KEY_ALL_ODDS_META)
    if meta and meta.get("events"):
        age = time.time() - meta.get("timestamp", 0)
        if age < STALE_TTL_ODDS:
            meta["_stale"] = True
            print(f"📦 Usando caché STALE ({meta.get('provider')}): {len(meta['events'])} partidos (edad: {int(age/3600)}h)")
            return meta["events"]

    # 5. Nada disponible — cachear vacio por 30 min para NO quemar creditos
    _cache_set(CACHE_KEY_ALL_ODDS_META, {
        "timestamp": time.time(),
        "provider": "none",
        "count": 0,
        "events": [],
    }, 1800)
    print("❌ Sin odds. Cache vacio por 30min para proteger creditos.")
    return []


def find_match_in_events(events: List[Dict], home_team: str, away_team: str) -> Optional[Dict]:
    """
    Busca un partido específico dentro de la lista de eventos cacheados.
    Usa coincidencia exacta (normalizada) primero, luego difusa.
    """
    for event in events:
        e_home = event.get("home_team", "")
        e_away = event.get("away_team", "")

        # Coincidencia exacta normalizada
        if normalize(e_home) == normalize(home_team) and normalize(e_away) == normalize(away_team):
            return event

        # Verificar también al revés (por si el API invierte el orden)
        if normalize(e_home) == normalize(away_team) and normalize(e_away) == normalize(home_team):
            # Invertir para mantener consistencia
            return _swap_event_teams(event)

    # Segunda pasada: coincidencia difusa
    for event in events:
        e_home = event.get("home_team", "")
        e_away = event.get("away_team", "")
        hm = fuzzy_match([e_home], home_team)
        aw = fuzzy_match([e_away], away_team)
        if hm and aw:
            return event
        # Probar al revés
        hm2 = fuzzy_match([e_home], away_team)
        aw2 = fuzzy_match([e_away], home_team)
        if hm2 and aw2:
            return _swap_event_teams(event)

    return None


def _swap_event_teams(event: Dict) -> Dict:
    """Invierte local/visitante en un evento (copia profunda)."""
    import copy
    swapped = copy.deepcopy(event)
    swapped["home_team"], swapped["away_team"] = swapped["away_team"], swapped["home_team"]
    # También invertir odds dentro de cada bookmaker
    for bk in swapped.get("bookmakers", []):
        for market in bk.get("markets", []):
            if market.get("key") == "h2h":
                outcomes = market.get("outcomes", [])
                home_outcome = None
                away_outcome = None
                others = []
                for o in outcomes:
                    name_lower = o.get("name", "").lower()
                    if name_lower in ["draw", "tie", "empate"]:
                        others.append(o)
                    elif home_outcome is None:
                        home_outcome = o
                    elif away_outcome is None:
                        away_outcome = o
                    else:
                        others.append(o)
                if home_outcome and away_outcome:
                    # Intercambiar
                    market["outcomes"] = [away_outcome] + others + [home_outcome]
    return swapped


# =============================================================================
# FUNCIÓN PÚBLICA: fetch_odds_for_match (REESCRITA — usa caché)
# =============================================================================

async def fetch_odds_for_match(home_team: str, away_team: str) -> Optional[Dict]:
    """
    Obtiene odds para un partido específico.
    ANTES: Hacía 1 llamada API por cada partido (¡caro!).
    AHORA: Busca en el caché (previamente poblado con 1 sola llamada).
    """
    events = await fetch_all_odds()
    if not events:
        return None

    match = find_match_in_events(events, home_team, away_team)
    if not match:
        return None

    return {
        "event_id": match.get("id"),
        "home_team": match.get("home_team", ""),
        "away_team": match.get("away_team", ""),
        "bookmakers": match.get("bookmakers", []),
        "_provider": match.get("_provider", "cache")
    }


# =============================================================================
# FUNCIONES DE PROCESAMIENTO (SIN CAMBIOS — compatibles con ambos proveedores)
# =============================================================================

def extract_odds_from_bookmaker(bookmaker: Dict, home_name: str, away_name: str) -> Dict:
    """
    Extrae odds del mercado h2h de un bookmaker.
    Busca outcomes cuyo nombre coincida con home_name, away_name o "Draw"/"Tie".
    """
    result = {"home_odds": None, "away_odds": None, "draw_odds": None}
    for market in bookmaker.get("markets", []):
        if market.get("key") != "h2h":
            continue
        for outcome in market.get("outcomes", []):
            name = outcome.get("name", "").strip()
            price = outcome.get("price")
            if price is None:
                continue
            name_lower = name.lower()
            home_lower = home_name.lower()
            away_lower = away_name.lower()
            if name_lower in ["draw", "tie", "empate", "x"]:
                result["draw_odds"] = float(price)
            elif name_lower == home_lower or home_lower in name_lower:
                result["home_odds"] = float(price)
            elif name_lower == away_lower or away_lower in name_lower:
                result["away_odds"] = float(price)
        break
    return result


def extract_top_bookmakers(bookmakers: List[Dict], home_name: str, away_name: str, limit: int = 3) -> List[Dict]:
    """Extrae los N bookmakers más importantes y sus odds."""
    if not bookmakers:
        return []

    def priority(bk):
        key = bk.get("key", "").lower()
        # Buscar en la lista de prioridad
        for i, pk in enumerate(PRIORITY_BOOKMAKERS):
            if pk in key or key in pk:
                return i
        return len(PRIORITY_BOOKMAKERS)

    sorted_bks = sorted(bookmakers, key=priority)
    top_bks = sorted_bks[:limit]
    result = []
    for bk in top_bks:
        odds = extract_odds_from_bookmaker(bk, home_name, away_name)
        # Solo incluir si tiene al menos una odd válida
        if any(odds.values()):
            result.append({
                "name": bk.get("title", bk.get("key", "Unknown")),
                "key": bk.get("key"),
                "home_odds": odds["home_odds"],
                "away_odds": odds["away_odds"],
                "draw_odds": odds["draw_odds"],
                "last_update": bk.get("last_update")
            })
    return result


def calculate_consensus(bookmakers: List[Dict], home_name: str, away_name: str) -> Dict:
    """Calcula odds de consenso promediando todas las casas."""
    home_odds, away_odds, draw_odds = [], [], []
    for bk in bookmakers:
        o = extract_odds_from_bookmaker(bk, home_name, away_name)
        if o["home_odds"]:
            home_odds.append(o["home_odds"])
        if o["away_odds"]:
            away_odds.append(o["away_odds"])
        if o["draw_odds"]:
            draw_odds.append(o["draw_odds"])
    return {
        "home_odds": round(sum(home_odds)/len(home_odds), 2) if home_odds else None,
        "away_odds": round(sum(away_odds)/len(away_odds), 2) if away_odds else None,
        "draw_odds": round(sum(draw_odds)/len(draw_odds), 2) if draw_odds else None,
        "num_bookmakers": len(bookmakers)
    }


def convert_decimal_to_probability(decimal_odds: float) -> float:
    return 1.0 / decimal_odds if decimal_odds and decimal_odds > 0 else 0.0


def estimate_score_from_odds(odds: Dict) -> Dict:
    """
    Estima el marcador más probable a partir de las probabilidades implícitas.
    (Sin cambios funcionales respecto a la versión original)
    """
    home_odds = odds.get("home_odds")
    away_odds = odds.get("away_odds")
    draw_odds = odds.get("draw_odds")

    home_prob = convert_decimal_to_probability(home_odds)
    away_prob = convert_decimal_to_probability(away_odds)
    draw_prob = convert_decimal_to_probability(draw_odds)

    total = home_prob + draw_prob + away_prob
    if total == 0:
        return {"home": 1, "away": 1, "score": "1-1", "home_prob": 0.333, "draw_prob": 0.333, "away_prob": 0.333}

    home_prob /= total
    draw_prob /= total
    away_prob /= total

    if home_odds is None and away_odds is None and draw_odds is not None:
        if draw_prob > 0.4:
            return {"home": 1, "away": 1, "score": "1-1", "home_prob": 0.35, "draw_prob": draw_prob, "away_prob": 0.35}
        else:
            return {"home": 0, "away": 0, "score": "0-0", "home_prob": 0.4, "draw_prob": draw_prob, "away_prob": 0.4}

    if home_odds is None:
        away_prob = away_prob / (away_prob + draw_prob) if (away_prob + draw_prob) > 0 else 0.5
        draw_prob = 1 - away_prob
        home_prob = 0
        if away_prob > 0.5:
            return {"home": 0, "away": 1, "score": "0-1", "home_prob": home_prob, "draw_prob": draw_prob, "away_prob": away_prob}
        else:
            return {"home": 1, "away": 1, "score": "1-1", "home_prob": home_prob, "draw_prob": draw_prob, "away_prob": away_prob}

    if away_odds is None:
        home_prob = home_prob / (home_prob + draw_prob) if (home_prob + draw_prob) > 0 else 0.5
        draw_prob = 1 - home_prob
        away_prob = 0
        if home_prob > 0.5:
            return {"home": 1, "away": 0, "score": "1-0", "home_prob": home_prob, "draw_prob": draw_prob, "away_prob": away_prob}
        else:
            return {"home": 1, "away": 1, "score": "1-1", "home_prob": home_prob, "draw_prob": draw_prob, "away_prob": away_prob}

    if home_prob > away_prob:
        lh = 1.2 + (home_prob - away_prob) * 1.5
        la = 1.0 - (home_prob - away_prob) * 0.5
    else:
        lh = 1.0 - (away_prob - home_prob) * 0.5
        la = 1.2 + (away_prob - home_prob) * 1.5

    lh = max(0.2, lh)
    la = max(0.2, la)

    try:
        from scipy.stats import poisson
        best_cell = (0, 0)
        best_p = 0.0
        for i in range(6):
            for j in range(6):
                p = poisson.pmf(i, lh) * poisson.pmf(j, la)
                if p > best_p:
                    best_p = p
                    best_cell = (i, j)
    except ImportError:
        best_cell = (round(lh), round(la))

    return {
        "home": best_cell[0],
        "away": best_cell[1],
        "score": f"{best_cell[0]}-{best_cell[1]}",
        "home_prob": round(home_prob, 4),
        "draw_prob": round(draw_prob, 4),
        "away_prob": round(away_prob, 4)
    }


def get_prediction_from_odds(odds: Dict) -> Dict:
    """Determina el pronóstico basado en las odds."""
    home_prob = convert_decimal_to_probability(odds.get("home_odds"))
    draw_prob = convert_decimal_to_probability(odds.get("draw_odds"))
    away_prob = convert_decimal_to_probability(odds.get("away_odds"))

    total = home_prob + draw_prob + away_prob
    if total == 0:
        return {"winner": None, "confidence": None, "home_prob": 0, "draw_prob": 0, "away_prob": 0}

    home_prob /= total
    draw_prob /= total
    away_prob /= total

    if home_prob > draw_prob and home_prob > away_prob:
        winner = "home"
        confidence = "Alta" if home_prob > 0.5 else "Media"
    elif away_prob > draw_prob:
        winner = "away"
        confidence = "Alta" if away_prob > 0.5 else "Media"
    else:
        winner = "draw"
        confidence = "Media"

    return {
        "winner": winner,
        "confidence": confidence,
        "home_prob": round(home_prob, 4),
        "draw_prob": round(draw_prob, 4),
        "away_prob": round(away_prob, 4)
    }


async def get_enriched_odds(home_team: str, away_team: str) -> Dict:
    """Obtiene odds enriquecidas para un partido. Interface sin cambios."""
    try:
        odds_data = await fetch_odds_for_match(home_team, away_team)
        if not odds_data:
            return {
                "top_bookmakers": [],
                "consensus": {},
                "prediction": {},
                "score_prediction": {},
                "available": False,
                "error": "No se pudieron obtener odds",
                "provider": None
            }

        bookmakers = odds_data.get("bookmakers", [])
        home_name = odds_data.get("home_team", "")
        away_name = odds_data.get("away_team", "")

        top_bks = extract_top_bookmakers(bookmakers, home_name, away_name, limit=3)
        consensus = calculate_consensus(bookmakers, home_name, away_name)
        prediction = get_prediction_from_odds(consensus)
        score_pred = estimate_score_from_odds(consensus)

        return {
            "top_bookmakers": top_bks,
            "consensus": consensus,
            "prediction": prediction,
            "score_prediction": score_pred,
            "available": bool(top_bks),
            "provider": odds_data.get("_provider", "unknown")
        }

    except Exception as e:
        print(f"❌ Error obteniendo odds para {home_team} vs {away_team}: {e}")
        return {
            "top_bookmakers": [],
            "consensus": {},
            "prediction": {},
            "score_prediction": {},
            "available": False,
            "error": str(e)[:80],
            "provider": None
        }


async def get_odds_status() -> Dict:
    """Retorna el estado actual del servicio de odds."""
    events = await fetch_all_odds()
    meta = _cache_get(CACHE_KEY_ALL_ODDS_META)

    age = 0
    provider = "none"
    count = 0
    is_stale = False

    if meta:
        age = time.time() - meta.get("timestamp", 0)
        provider = meta.get("provider", "unknown")
        count = meta.get("count", 0)
        is_stale = meta.get("_stale", False)

    if events:
        count = len(events)

    unique_bks = set()
    for evt in (events or []):
        for bk in evt.get("bookmakers", []):
            unique_bks.add(bk.get("key", ""))

    return {
        "provider": provider,
        "events_count": count,
        "unique_bookmakers": len(unique_bks),
        "bookmakers": list(unique_bks)[:15],
        "cache_age_seconds": round(age),
        "cache_age_human": f"{int(age // 3600)}h {int((age % 3600) // 60)}m",
        "is_stale": is_stale,
        "cache_ttl_seconds": CACHE_TTL_ODDS,
        "stale_ttl_seconds": STALE_TTL_ODDS,
        "papi_configured": bool(ODDS_PAPI_API_KEY),
        "toa_configured": bool(ODDS_API_KEY),
    }
