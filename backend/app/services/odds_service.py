# =============================================================================
# odds_service.py  —  THE ODDS API + CACHÉ AGRESIVO
# =============================================================================
# 1 sola petición API → cachea TODAS las odds → distribuye a cada partido
# Con caché de 8h = ~90 peticiones/mes (plan gratis = 500)
# =============================================================================

import httpx
import os
import time
import difflib
import json
from typing import List, Dict, Optional, Any
from app.config import ODDS_API_KEY

try:
    from app.cache.redis_client import cache_get, cache_set, redis_client
except ImportError:
    redis_client = None
    cache_get = None
    cache_set = None

# ── Constantes ──────────────────────────────────────────────────────────────
CACHE_KEY_META = "wc2026:all_odds_meta"
CACHE_TTL = 8 * 3600
STALE_TTL = 48 * 3600

TOA_BASE = "https://api.the-odds-api.com/v4"
TOA_SPORT = "soccer_fifa_world_cup"
TOA_REGIONS = "us,uk,eu"
TOA_MARKETS = "h2h"

PRIORITY_BOOKMAKERS = [
    "pinnacle", "bet365", "fanduel", "draftkings", "betmgm",
    "caesars", "williamhill", "unibet", "1xbet", "betfair"
]

TEAM_SYNONYMS = {
    "Rep. Dem. del Congo": "Congo DR", "Congo": "Congo DR", "RD Congo": "Congo DR",
    "DR Congo": "Congo DR", "Estados Unidos": "USA", "United States": "USA",
    "US": "USA", "Corea del Sur": "South Korea", "South Korea": "South Korea",
    "Korea Republic": "South Korea", "Korea": "South Korea",
    "Países Bajos": "Netherlands", "Holanda": "Netherlands",
    "República Checa": "Czech Republic", "Czechia": "Czech Republic",
    "Costa de Marfil": "Ivory Coast", "Cote d'Ivoire": "Ivory Coast",
    "Arabia Saudita": "Saudi Arabia", "Saudi": "Saudi Arabia",
    "Nueva Zelanda": "New Zealand", "Cabo Verde": "Cape Verde",
    "Bosnia y Herzegovina": "Bosnia and Herzegovina", "Bosnia": "Bosnia and Herzegovina",
    "Inglaterra": "England", "Irán": "Iran", "Turquía": "Turkey",
    "Japón": "Japan", "Marruecos": "Morocco", "Brasil": "Brazil",
    "Argentina": "Argentina", "Francia": "France", "Alemania": "Germany",
    "España": "Spain", "Portugal": "Portugal", "Uruguay": "Uruguay",
    "Colombia": "Colombia", "México": "Mexico", "Ecuador": "Ecuador",
    "Perú": "Peru", "Chile": "Chile", "Paraguay": "Paraguay",
    "Túnez": "Tunisia", "Egipto": "Egypt", "Senegal": "Senegal",
    "Camerún": "Cameroon", "Cameroon": "Cameroon", "Ghana": "Ghana",
    "Nigeria": "Nigeria", "Costa Rica": "Costa Rica", "Panamá": "Panama",
    "Panama": "Panama", "Canadá": "Canada", "Haití": "Haiti",
    "Curazao": "Curaçao", "Curaçao": "Curacao", "Curacao": "Curaçao",
    "Escocia": "Scotland", "Suecia": "Sweden", "Noruega": "Norway",
    "Bélgica": "Belgium", "Austria": "Austria", "Croacia": "Croatia",
    "Suiza": "Switzerland", "Serbia": "Serbia", "Dinamarca": "Denmark",
    "Polonia": "Poland", "Ucrania": "Ukraine", "Rumanía": "Romania",
    "Rusia": "Russia", "Eslovaquia": "Slovakia", "Eslovenia": "Slovenia",
    "Australia": "Australia", "China": "China", "Emiratos Árabes": "UAE",
    "UAE": "UAE", "Irak": "Iraq", "Iraq": "Iraq", "Jordania": "Jordan",
    "Argelia": "Algeria", "Algeria": "Algeria", "Sudáfrica": "South Africa",
    "South Africa": "South Africa", "Qatar": "Qatar", "Catar": "Qatar",
    "Uzbekistán": "Uzbekistan", "Uzbekistan": "Uzbekistan",
    "Democratic Republic of the Congo": "Congo DR",
}


# =============================================================================
# NORMALIZACIÓN
# =============================================================================

def normalize(name: str) -> str:
    import unicodedata
    if not name:
        return ""
    name = name.strip().lower()
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    name = name.replace("-", " ").replace("(", " ").replace(")", " ")
    for our, api in TEAM_SYNONYMS.items():
        if _raw(our) == name:
            return _raw(api)
    return name

def _raw(name: str) -> str:
    import unicodedata
    name = name.strip().lower()
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    return name.replace("-", " ").replace("(", " ").replace(")", " ")

def fuzzy_match(teams: List[str], search: str, threshold=0.75) -> Optional[str]:
    s = normalize(search)
    best, best_r = None, 0
    for t in teams:
        r = difflib.SequenceMatcher(None, s, normalize(t)).ratio()
        if r > best_r:
            best_r, best = r, t
    return best if best_r >= threshold else None


# =============================================================================
# CACHÉ (Redis + memoria)
# =============================================================================

_mem: Dict[str, Any] = {}

def _get(key: str) -> Optional[Any]:
    if key in _mem:
        return _mem[key]
    if cache_get and redis_client:
        try:
            raw = cache_get(key)
            if raw:
                return json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            pass
    return _mem.get(key)

def _set(key: str, val: Any, ttl: int):
    _mem[key] = val
    if cache_set and redis_client:
        try:
            cache_set(key, json.dumps(val) if isinstance(val, (dict, list)) else val, ttl)
        except Exception:
            pass


# =============================================================================
# OBTENER TODAS LAS ODDS (1 sola petición API)
# =============================================================================

async def fetch_all_odds(force_refresh: bool = False) -> List[Dict]:
    # 1. Caché fresco
    if not force_refresh:
        meta = _get(CACHE_KEY_META)
        if meta and meta.get("events"):
            age = time.time() - meta.get("timestamp", 0)
            if age < CACHE_TTL and not meta.get("_stale"):
                print(f"📦 Caché odds: {len(meta['events'])} partidos ({int(age/60)}min)")
                return meta["events"]

    # 2. The Odds API
    if ODDS_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{TOA_BASE}/sports/{TOA_SPORT}/odds", params={
                    "apiKey": ODDS_API_KEY, "regions": TOA_REGIONS,
                    "markets": TOA_MARKETS, "oddsFormat": "decimal"
                })
                if resp.status_code == 429:
                    print("⚠️ The Odds API: 429 (créditos agotados)")
                elif resp.status_code == 401:
                    print("⚠️ The Odds API: 401 (key inválida)")
                else:
                    resp.raise_for_status()
                    events = resp.json()
                    if events:
                        for e in events:
                            e["_provider"] = "the_odds_api"
                        _set(CACHE_KEY_META, {
                            "timestamp": time.time(), "provider": "the_odds_api",
                            "count": len(events), "events": events
                        }, CACHE_TTL)
                        print(f"✅ The Odds API: {len(events)} partidos")
                        return events
        except httpx.HTTPStatusError:
            pass
        except Exception as e:
            print(f"❌ The Odds API: {e}")

    # 3. Caché stale
    meta = _get(CACHE_KEY_META)
    if meta and meta.get("events"):
        age = time.time() - meta.get("timestamp", 0)
        if age < STALE_TTL:
            print(f"📦 Caché stale: {len(meta['events'])} partidos ({int(age/3600)}h)")
            return meta["events"]

    print("❌ Sin odds disponibles")
    return []


def find_match(events: List[Dict], home: str, away: str) -> Optional[Dict]:
    for e in events:
        eh, ea = e.get("home_team", ""), e.get("away_team", "")
        if normalize(eh) == normalize(home) and normalize(ea) == normalize(away):
            return e
        if normalize(eh) == normalize(away) and normalize(ea) == normalize(home):
            return _swap(e)
    for e in events:
        eh, ea = e.get("home_team", ""), e.get("away_team", "")
        hm, am = fuzzy_match([eh], home), fuzzy_match([ea], away)
        if hm and am:
            return e
        hm2, am2 = fuzzy_match([eh], away), fuzzy_match([ea], home)
        if hm2 and am2:
            return _swap(e)
    return None

def _swap(e: Dict) -> Dict:
    import copy
    s = copy.deepcopy(e)
    s["home_team"], s["away_team"] = s["away_team"], s["home_team"]
    for bk in s.get("bookmakers", []):
        for m in bk.get("markets", []):
            if m.get("key") == "h2h":
                outs = m.get("outcomes", [])
                h_o = a_o = None
                others = []
                for o in outs:
                    nl = o.get("name", "").lower()
                    if nl in ["draw", "tie", "empate"]:
                        others.append(o)
                    elif h_o is None:
                        h_o = o
                    elif a_o is None:
                        a_o = o
                    else:
                        others.append(o)
                if h_o and a_o:
                    m["outcomes"] = [a_o] + others + [h_o]
    return s


# =============================================================================
# FUNCIÓN PÚBLICA
# =============================================================================

async def fetch_odds_for_match(home: str, away: str) -> Optional[Dict]:
    events = await fetch_all_odds()
    if not events:
        return None
    m = find_match(events, home, away)
    if not m:
        return None
    return {
        "event_id": m.get("id"), "home_team": m.get("home_team", ""),
        "away_team": m.get("away_team", ""), "bookmakers": m.get("bookmakers", []),
        "_provider": m.get("_provider", "cache")
    }

def extract_odds_from_bookmaker(bk: Dict, home: str, away: str) -> Dict:
    result = {"home_odds": None, "away_odds": None, "draw_odds": None}
    for m in bk.get("markets", []):
        if m.get("key") != "h2h":
            continue
        for o in m.get("outcomes", []):
            name = o.get("name", "").strip()
            price = o.get("price")
            if price is None:
                continue
            nl = name.lower()
            if nl in ["draw", "tie", "empate", "x"]:
                result["draw_odds"] = float(price)
            elif nl == home.lower() or home.lower() in nl:
                result["home_odds"] = float(price)
            elif nl == away.lower() or away.lower() in nl:
                result["away_odds"] = float(price)
        break
    return result

def extract_top_bookmakers(bks: List[Dict], home: str, away: str, limit: int = 3) -> List[Dict]:
    if not bks:
        return []
    def prio(bk):
        k = bk.get("key", "").lower()
        for i, p in enumerate(PRIORITY_BOOKMAKERS):
            if p in k or k in p:
                return i
        return len(PRIORITY_BOOKMAKERS)
    result = []
    for bk in sorted(bks, key=prio)[:limit]:
        o = extract_odds_from_bookmaker(bk, home, away)
        if any(o.values()):
            result.append({"name": bk.get("title", bk.get("key", "?")),
                           "key": bk.get("key"), **o,
                           "last_update": bk.get("last_update")})
    return result

def calculate_consensus(bks: List[Dict], home: str, away: str) -> Dict:
    h, a, d = [], [], []
    for bk in bks:
        o = extract_odds_from_bookmaker(bk, home, away)
        if o["home_odds"]: h.append(o["home_odds"])
        if o["away_odds"]: a.append(o["away_odds"])
        if o["draw_odds"]: d.append(o["draw_odds"])
    return {
        "home_odds": round(sum(h)/len(h), 2) if h else None,
        "away_odds": round(sum(a)/len(a), 2) if a else None,
        "draw_odds": round(sum(d)/len(d), 2) if d else None,
        "num_bookmakers": len(bks)
    }

def convert_decimal_to_probability(o: float) -> float:
    return 1.0 / o if o and o > 0 else 0.0

def estimate_score_from_odds(odds: Dict) -> Dict:
    ho, ao, do = odds.get("home_odds"), odds.get("away_odds"), odds.get("draw_odds")
    hp, ap, dp = convert_decimal_to_probability(ho), convert_decimal_to_probability(ao), convert_decimal_to_probability(do)
    t = hp + dp + ap
    if t == 0:
        return {"home": 1, "away": 1, "score": "1-1", "home_prob": .333, "draw_prob": .333, "away_prob": .333}
    hp /= t; dp /= t; ap /= t
    if ho is None and ao is None and do is not None:
        s = "1-1" if dp > .4 else "0-0"
        v = .35 if dp > .4 else .4
        return {"home": int(s[0]), "away": int(s[2]), "score": s, "home_prob": v, "draw_prob": dp, "away_prob": v}
    if ho is None:
        ap2 = ap/(ap+dp) if (ap+dp) > 0 else .5; dp2 = 1-ap2; hp2 = 0
        s = "0-1" if ap2 > .5 else "1-1"
        return {"home": int(s[0]), "away": int(s[2]), "score": s, "home_prob": hp2, "draw_prob": dp2, "away_prob": ap2}
    if ao is None:
        hp2 = hp/(hp+dp) if (hp+dp) > 0 else .5; dp2 = 1-hp2; ap2 = 0
        s = "1-0" if hp2 > .5 else "1-1"
        return {"home": int(s[0]), "away": int(s[2]), "score": s, "home_prob": hp2, "draw_prob": dp2, "away_prob": ap2}
    lh = 1.2 + (hp - ap) * 1.5 if hp > ap else 1.0 - (ap - hp) * 0.5
    la = 1.0 - (hp - ap) * 0.5 if hp > ap else 1.2 + (ap - hp) * 1.5
    lh, la = max(0.2, lh), max(0.2, la)
    try:
        from scipy.stats import poisson
        bc, bp = (0, 0), 0.0
        for i in range(6):
            for j in range(6):
                p = poisson.pmf(i, lh) * poisson.pmf(j, la)
                if p > bp: bp, bc = p, (i, j)
    except ImportError:
        bc = (round(lh), round(la))
    return {"home": bc[0], "away": bc[1], "score": f"{bc[0]}-{bc[1]}", "home_prob": round(hp, 4), "draw_prob": round(dp, 4), "away_prob": round(ap, 4)}

def get_prediction_from_odds(odds: Dict) -> Dict:
    hp, dp, ap = convert_decimal_to_probability(odds.get("home_odds")), convert_decimal_to_probability(odds.get("draw_odds")), convert_decimal_to_probability(odds.get("away_odds"))
    t = hp + dp + ap
    if t == 0:
        return {"winner": None, "confidence": None, "home_prob": 0, "draw_prob": 0, "away_prob": 0}
    hp /= t; dp /= t; ap /= t
    if hp > dp and hp > ap:
        return {"winner": "home", "confidence": "Alta" if hp > .5 else "Media", "home_prob": round(hp, 4), "draw_prob": round(dp, 4), "away_prob": round(ap, 4)}
    if ap > dp:
        return {"winner": "away", "confidence": "Alta" if ap > .5 else "Media", "home_prob": round(hp, 4), "draw_prob": round(dp, 4), "away_prob": round(ap, 4)}
    return {"winner": "draw", "confidence": "Media", "home_prob": round(hp, 4), "draw_prob": round(dp, 4), "away_prob": round(ap, 4)}

async def get_enriched_odds(home: str, away: str) -> Dict:
    try:
        data = await fetch_odds_for_match(home, away)
        if not data:
            return {"top_bookmakers": [], "consensus": {}, "prediction": {}, "score_prediction": {}, "available": False, "error": "No se pudieron obtener odds", "provider": None}
        bks = data.get("bookmakers", [])
        hn, an = data.get("home_team", ""), data.get("away_team", "")
        c = calculate_consensus(bks, hn, an)
        return {"top_bookmakers": extract_top_bookmakers(bks, hn, an), "consensus": c, "prediction": get_prediction_from_odds(c), "score_prediction": estimate_score_from_odds(c), "available": True, "provider": data.get("_provider", "unknown")}
    except Exception as e:
        print(f"❌ Odds error {home} vs {away}: {e}")
        return {"top_bookmakers": [], "consensus": {}, "prediction": {}, "score_prediction": {}, "available": False, "error": str(e)[:80], "provider": None}

async def get_odds_status() -> Dict:
    events = await fetch_all_odds()
    meta = _get(CACHE_KEY_META)
    age = time.time() - meta.get("timestamp", 0) if meta else 0
    ub = set()
    for e in (events or []):
        for b in e.get("bookmakers", []):
            ub.add(b.get("key", ""))
    return {"provider": meta.get("provider", "none") if meta else "none", "events_count": len(events) if events else 0, "unique_bookmakers": len(ub), "bookmakers": list(ub)[:15], "cache_age_seconds": round(age), "cache_age_human": f"{int(age//3600)}h {int((age%3600)//60)}m", "toa_configured": bool(ODDS_API_KEY)}
