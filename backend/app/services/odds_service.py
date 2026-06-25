import httpx
import os
import difflib
from typing import List, Dict, Optional
from app.config import ODDS_API_KEY

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_SPORT = "soccer_fifa_world_cup"
ODDS_REGIONS = "us,uk,eu"
ODDS_MARKETS = "h2h"
PRIORITY_BOOKMAKERS = ["fanduel", "draftkings", "betmgm", "caesars", "williamhill", "unibet", "pinnacle"]

# Sinónimos para normalizar nombres de equipos (nuestro sistema -> nombre en la API)
TEAM_SYNONYMS = {
    "Rep. Dem. del Congo": "Congo DR",
    "Congo": "Congo DR",
    "Estados Unidos": "USA",
    "United States": "USA",
    "Corea del Sur": "South Korea",
    "Países Bajos": "Netherlands",
    "República Checa": "Czech Republic",
    "Costa de Marfil": "Ivory Coast",
    "Arabia Saudita": "Saudi Arabia",
    "Nueva Zelanda": "New Zealand",
    "Cabo Verde": "Cape Verde",
    "Bosnia y Herzegovina": "Bosnia and Herzegovina",
    "Inglaterra": "England",
}

def normalize(name: str) -> str:
    """Normaliza y mapea nombres para comparación."""
    import unicodedata
    name = name.strip().lower()
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('utf-8')
    for our, api in TEAM_SYNONYMS.items():
        if our.lower() in name:
            return api.lower()
    return name

def fuzzy_match(event_teams: List[str], search: str, threshold=0.8) -> Optional[str]:
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

async def fetch_odds_for_match(home_team: str, away_team: str) -> Optional[Dict]:
    """Obtiene odds de la API para un partido específico."""
    if not ODDS_API_KEY:
        print("⚠️ ODDS_API_KEY no configurada.")
        return None
    try:
        url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": ODDS_REGIONS,
            "markets": ODDS_MARKETS,
            "oddsFormat": "decimal"
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            events = response.json()

        for event in events:
            e_home = event.get("home_team", "")
            e_away = event.get("away_team", "")

            # Coincidencia exacta (normalizada)
            if normalize(e_home) == normalize(home_team) and normalize(e_away) == normalize(away_team):
                return {
                    "event_id": event.get("id"),
                    "home_team": e_home,
                    "away_team": e_away,
                    "bookmakers": event.get("bookmakers", [])
                }

            # Coincidencia difusa
            hm = fuzzy_match([e_home], home_team)
            aw = fuzzy_match([e_away], away_team)
            if hm and aw:
                return {
                    "event_id": event.get("id"),
                    "home_team": e_home,
                    "away_team": e_away,
                    "bookmakers": event.get("bookmakers", [])
                }
        return None
    except Exception as e:
        print(f"❌ Error obteniendo odds: {e}")
        return None

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
            # Identificar si es local, visitante o empate
            name_lower = name.lower()
            home_lower = home_name.lower()
            away_lower = away_name.lower()
            if name_lower in ["draw", "tie", "empate"]:
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
        if key in PRIORITY_BOOKMAKERS:
            return PRIORITY_BOOKMAKERS.index(key)
        return len(PRIORITY_BOOKMAKERS)

    sorted_bks = sorted(bookmakers, key=priority)
    top_bks = sorted_bks[:limit]
    result = []
    for bk in top_bks:
        odds = extract_odds_from_bookmaker(bk, home_name, away_name)
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
    Si solo hay draw_odds, asume un partido equilibrado.
    """
    home_odds = odds.get("home_odds")
    away_odds = odds.get("away_odds")
    draw_odds = odds.get("draw_odds")

    home_prob = convert_decimal_to_probability(home_odds)
    away_prob = convert_decimal_to_probability(away_odds)
    draw_prob = convert_decimal_to_probability(draw_odds)

    total = home_prob + draw_prob + away_prob
    if total == 0:
        # Sin odds: partido equilibrado
        return {"home": 1, "away": 1, "score": "1-1", "home_prob": 0.333, "draw_prob": 0.333, "away_prob": 0.333}

    home_prob /= total
    draw_prob /= total
    away_prob /= total

    # Si no hay odds de local o visitante, estimamos a partir de draw_odds
    if home_odds is None and away_odds is None and draw_odds is not None:
        # Solo odds de empate: partido muy igualado, asumimos 1-1 o 0-0
        if draw_prob > 0.4:
            return {"home": 1, "away": 1, "score": "1-1", "home_prob": 0.35, "draw_prob": draw_prob, "away_prob": 0.35}
        else:
            return {"home": 0, "away": 0, "score": "0-0", "home_prob": 0.4, "draw_prob": draw_prob, "away_prob": 0.4}

    # Si solo hay draw_odds y una de las otras, usamos la que exista
    if home_odds is None:
        # Solo away y draw
        away_prob = away_prob / (away_prob + draw_prob) if (away_prob + draw_prob) > 0 else 0.5
        draw_prob = 1 - away_prob
        home_prob = 0
        # Asumimos que el visitante es favorito si away_prob > 0.5
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

    # Caso normal: tenemos las tres odds
    # Estimamos goles esperados a partir de las probabilidades
    # Usamos una heurística simple: si home_prob > away_prob, local favorito
    if home_prob > away_prob:
        lh = 1.2 + (home_prob - away_prob) * 1.5
        la = 1.0 - (home_prob - away_prob) * 0.5
    else:
        lh = 1.0 - (away_prob - home_prob) * 0.5
        la = 1.2 + (away_prob - home_prob) * 1.5

    lh = max(0.2, lh)
    la = max(0.2, la)

    # Buscar marcador más probable con Poisson
    from scipy.stats import poisson
    best_cell = (0, 0)
    best_p = 0.0
    for i in range(6):
        for j in range(6):
            p = poisson.pmf(i, lh) * poisson.pmf(j, la)
            if p > best_p:
                best_p = p
                best_cell = (i, j)

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
    """Obtiene odds enriquecidas para un partido con manejo de errores silencioso."""
    try:
        odds_data = await fetch_odds_for_match(home_team, away_team)
        if not odds_data:
            return {
                "top_bookmakers": [],
                "consensus": {},
                "prediction": {},
                "score_prediction": {},
                "available": False,
                "error": "No se pudieron obtener odds"
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
            "available": True
        }

    except Exception as e:
        print(f"❌ Error obteniendo odds para {home_team} vs {away_team}: {e}")
        return {
            "top_bookmakers": [],
            "consensus": {},
            "prediction": {},
            "score_prediction": {},
            "available": False,
            "error": str(e)[:50]
        }
