import math
import random
from itertools import combinations
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter

from app.models.dixon_coles import elo_to_lambda

try:
    from app.services.prediction_service import elo_manager
except Exception:
    elo_manager = None

router = APIRouter(prefix="/api/v1")

# ============================================================================
# CONFIG - 2026 WORLD CUP FORMAT (12 Groups, 48 Teams)
# ============================================================================

GROUPS: Dict[str, List[str]] = {
    "A": ["Mexico", "South Korea", "South Africa", "Czech Republic"],
    "B": ["Canada", "Switzerland", "Qatar", "Bosnia and Herzegovina"],
    "C": ["Brazil", "Morocco", "Scotland", "Haiti"],
    "D": ["United States", "Australia", "Paraguay", "Türkiye"],
    "E": ["Germany", "Curacao", "Cote d'Ivoire", "Ecuador"],
    "F": ["Netherlands", "Japan", "Tunisia", "Sweden"],
    "G": ["Belgium", "Iran", "Egypt", "New Zealand"],
    "H": ["Spain", "Uruguay", "Saudi Arabia", "Cape Verde"],
    "I": ["France", "Senegal", "Norway", "Iraq"],
    "J": ["Argentina", "Austria", "Algeria", "Jordan"],
    "K": ["Portugal", "Colombia", "Uzbekistan", "Democratic Republic of the Congo"],
    "L": ["England", "Croatia", "Panama", "Ghana"],
}

DEFAULT_SIMULATIONS = 5000
MAX_SIMULATIONS = 100000

# En Mundial 2026, hay localía real para Estados Unidos, México y Canadá.
HOSTS = {"Mexico", "Canada", "United States"}
HOME_ADVANTAGE_ELO_BOOST = 50  # Equivalente a ~0.15 goles extra de expectativa

# ============================================================================
# HELPERS & MATH MODELS
# ============================================================================

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

def get_rating(team: str) -> float:
    if elo_manager and hasattr(elo_manager, "get_rating"):
        try:
            return float(elo_manager.get_rating(team))
        except Exception:
            pass
    return 1500.0

def poisson_sample(lmbda: float, rng: random.Random) -> int:
    lmbda = max(0.01, float(lmbda))
    limit = math.exp(-lmbda)
    k = 0
    p = 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1

def expected_goals(team_a: str, team_b: str) -> Tuple[float, float]:
    """
    Modelo estadístico riguroso para calcular medias de Poisson (λ).
    Usa la transformación logarítmica estándar de Elo: λ = μ * 10^((Elo_a - Elo_b) / 400)
    donde μ es la media histórica de goles por equipo en mundiales (~1.35).
    """
    elo_a = get_rating(team_a) + (HOME_ADVANTAGE_ELO_BOOST if team_a in HOSTS else 0)
    elo_b = get_rating(team_b) + (HOME_ADVANTAGE_ELO_BOOST if team_b in HOSTS else 0)

    # Media base de goles en mundiales
    mu = 1.35

    # Probabilidad implícita y mapeo a expected goals
    delta_elo = elo_a - elo_b
    lambda_a = mu * (10 ** (delta_elo / 800))
    lambda_b = mu * (10 ** (-delta_elo / 800))

    # Clamps estadísticamente seguros (evitar varianza irreal, pero permitiendo goleadas)
    return (
        clamp(float(lambda_a), 0.25, 4.0),
        clamp(float(lambda_b), 0.25, 4.0),
    )

def fair_play_score(team: dict) -> int:
    # Menor es mejor en fair play. Si no hay modelo, 0 es neutral.
    return int(team.get("fair_play", 0))


# ============================================================================
# MATCH SIMULATION (90 min & Extra Time)
# ============================================================================

def simulate_match(team_a: str, team_b: str, rng: random.Random, time_factor: float = 1.0) -> Tuple[int, int]:
    """
    time_factor: 1.0 para 90 mins, ~0.33 para 30 mins de prórroga.
    """
    lam_a, lam_b = expected_goals(team_a, team_b)
    goals_a = poisson_sample(lam_a * time_factor, rng)
    goals_b = poisson_sample(lam_b * time_factor, rng)
    return goals_a, goals_b

def simulate_group_match(team_a: str, team_b: str, rng: random.Random) -> Dict:
    goals_a, goals_b = simulate_match(team_a, team_b, rng, time_factor=1.0)

    if goals_a > goals_b:
        points_a, points_b = 3, 0
        result_a, result_b = "win", "loss"
    elif goals_b > goals_a:
        points_a, points_b = 0, 3
        result_a, result_b = "loss", "win"
    else:
        points_a, points_b = 1, 1
        result_a = result_b = "draw"

    return {
        "team_a": team_a, "team_b": team_b,
        "goals_a": goals_a, "goals_b": goals_b,
        "points_a": points_a, "points_b": points_b,
        "result_a": result_a, "result_b": result_b,
    }

def simulate_knockout_match(team_a: str, team_b: str, rng: random.Random) -> Dict:
    """
    Reglas FIFA: Si empatan a los 90', Prórroga de 30 mins. Si persiste, Penales.
    """
    goals_a, goals_b = simulate_match(team_a, team_b, rng, time_factor=1.0)
    et_goals_a, et_goals_b = 0, 0
    won_on_penalties = False
    winner = team_a if goals_a > goals_b else team_b

    if goals_a == goals_b:
        # Prórroga (30 minutos -> time_factor ~ 1/3)
        et_goals_a, et_goals_b = simulate_match(team_a, team_b, rng, time_factor=0.33)
        total_a = goals_a + et_goals_a
        total_b = goals_b + et_goals_b

        if total_a == total_b:
            # Penales: Modelo sesgado por Elo
            won_on_penalties = True
            elo_a = get_rating(team_a)
            elo_b = get_rating(team_b)
            p_a = 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))
            winner = team_a if rng.random() < p_a else team_b
        else:
            winner = team_a if total_a > total_b else team_b

    return {
        "team_a": team_a, "team_b": team_b,
        "goals_a": goals_a, "goals_b": goals_b,
        "et_goals_a": et_goals_a, "et_goals_b": et_goals_b,
        "penalties": won_on_penalties,
        "winner": winner,
    }


# ============================================================================
# FIFA GROUP TIEBREAKERS (Art 10.4 FIFA World Cup Regulations)
# ============================================================================

def _h2h_subset(team_names: set[str], matches: List[dict]) -> Dict[str, Dict[str, int]]:
    stats = {team: {"points": 0, "gf": 0, "ga": 0, "gd": 0} for team in team_names}
    for m in matches:
        a, b = m["team_a"], m["team_b"]
        if a in team_names and b in team_names:
            ga, gb = m["goals_a"], m["goals_b"]
            stats[a]["gf"] += ga; stats[a]["ga"] += gb
            stats[b]["gf"] += gb; stats[b]["ga"] += ga
            if ga > gb: stats[a]["points"] += 3
            elif gb > ga: stats[b]["points"] += 3
            else: stats[a]["points"] += 1; stats[b]["points"] += 1
    for t in team_names: stats[t]["gd"] = stats[t]["gf"] - stats[t]["ga"]
    return stats

def apply_fifa_tiebreakers(group_table: List[Dict], matches: List[dict], rng: random.Random) -> List[Dict]:
    if len(group_table) <= 1:
        return group_table

    # Asignar sorteo aleatorio fijo por simulación para desempate final
    for t in group_table:
        t["lottery"] = rng.random()

    # 1. Orden básico FIFA (Puntos, DG, GF)
    ordered = sorted(group_table, key=lambda t: (-t["points"], -t["gd"], -t["gf"]))

    final_order = []
    i = 0
    while i < len(ordered):
        j = i + 1
        # Identificar bloque empate en Puntos, DG, GF
        while j < len(ordered) and ordered[i]["points"] == ordered[j]["points"] \
              and ordered[i]["gd"] == ordered[j]["gd"] and ordered[i]["gf"] == ordered[j]["gf"]:
            j += 1

        tied_block = ordered[i:j]

        if len(tied_block) == 1:
            final_order.extend(tied_block)
        else:
            # Aplicar H2H entre los empatados
            tied_names = {t["team"] for t in tied_block}
            h2h = _h2h_subset(tied_names, matches)

            def h2h_key(team: Dict) -> Tuple:
                name = team["team"]
                return (
                    -h2h[name]["points"],
                    -h2h[name]["gd"],
                    -h2h[name]["gf"],
                    fair_play_score(team),
                    team["lottery"] # Sorteo estricto
                )

            tied_block = sorted(tied_block, key=h2h_key)
            final_order.extend(tied_block)
        i = j

    return final_order


# ============================================================================
# GROUP STAGE
# ============================================================================

def build_group_table(group_letter: str, teams: List[str], rng: random.Random) -> Tuple[List[Dict], List[dict]]:
    stats = {
        team: {"team": team, "group": group_letter, "points": 0, "gf": 0, "ga": 0, "gd": 0, "fair_play": 0, "matches": []}
        for team in teams
    }
    matches = []

    for team_a, team_b in combinations(teams, 2):
        result = simulate_group_match(team_a, team_b, rng)
        matches.append({"team_a": team_a, "team_b": team_b, "goals_a": result["goals_a"], "goals_b": result["goals_b"]})

        a, b = stats[team_a], stats[team_b]
        a["gf"] += result["goals_a"]; a["ga"] += result["goals_b"]; a["gd"] = a["gf"] - a["ga"]; a["points"] += result["points_a"]
        b["gf"] += result["goals_b"]; b["ga"] += result["goals_a"]; b["gd"] = b["gf"] - b["ga"]; b["points"] += result["points_b"]

    table = list(stats.values())
    table = apply_fifa_tiebreakers(table, matches, rng)
    return table, matches

def simulate_group_stage(groups: Dict[str, List[str]], rng: random.Random) -> Dict:
    standings, group_matches, group_winners, group_runners_up, third_placed = {}, {}, [], [], []

    for group_letter, teams in groups.items():
        table, matches = build_group_table(group_letter, teams, rng)
        standings[group_letter] = table
        group_matches[group_letter] = matches
        if len(table) > 0: group_winners.append({**table[0], "position": 1})
        if len(table) > 1: group_runners_up.append({**table[1], "position": 2})
        if len(table) > 2: third_placed.append({**table[2], "position": 3})

    # Regla FIFA 2026: Clasifican los 8 mejores terceros
    best_third = sorted(
        third_placed,
        key=lambda t: (-t["points"], -t["gd"], -t["gf"], fair_play_score(t), t.get("lottery", 0))
    )[:8]

    qualified = group_winners + group_runners_up + best_third
    return {
        "standings": standings, "group_matches": group_matches,
        "group_winners": group_winners, "group_runners_up": group_runners_up,
        "third_placed": third_placed, "best_third": best_third, "qualified": qualified
    }


# ============================================================================
# KNOCKOUT STAGE (2026 Official Bracket Algorithm)
# ============================================================================

def build_official_bracket(qualified: List[Dict]) -> List[Dict]:
    """
    Genera el bracket oficial de la FIFA para 32 equipos.
    Evita que equipos del mismo grupo se enfrenten en Ronda de 32.
    """
    winners = {t["team"]: t for t in qualified if t["position"] == 1}
    runners = {t["team"]: t for t in qualified if t["position"] == 2}
    thirds = {t["team"]: t for t in qualified if t["position"] == 3}

    # 8 enfrentamientos de 1 vs 2 (Protegidos por Grupo)
    matches_w_r = [
        (f"1{g}", f"2{chr(ord(g)+1)}") for g in "ACEGIK" # 1A vs 2B, 1C vs 2D...
    ]

    # 8 enfrentamientos para los mejores terceros
    matches_w_3 = [
        (f"1B", "3rd"), (f"1D", "3rd"), (f"1F", "3rd"), (f"1H", "3rd"),
        (f"2A", "3rd"), (f"2C", "3rd"), (f"2E", "3rd"), (f"2G", "3rd")
    ]

    # Asignar terceros evitando conflicto de grupo
    available_thirds = list(thirds.values())
    assigned_matchups = []

    for slot_1, slot_2 in matches_w_3:
        slot_group = slot_1[1] # Letra del grupo del cabeza de serie
        assigned_team = None

        for i, third_team in enumerate(available_thirds):
            if third_team["group"] != slot_group: # Restricción FIFA
                assigned_team = available_thirds.pop(i)
                break

        if assigned_team:
            if slot_1.startswith("1"):
                assigned_matchups.append((winners[f"1{slot_group}"]["team"], assigned_team["team"]))
            else:
                assigned_matchups.append((runners[f"2{slot_group}"]["team"], assigned_team["team"]))

    # Construir Ronda de 32 final
    r32_matchups = []
    for w, r in matches_w_r:
        if w in winners and r in runners:
            r32_matchups.append((winners[w]["team"], runners[r]["team"]))

    r32_matchups.extend(assigned_matchups)

    # Mapear a objetos equipo
    team_map = {t["team"]: t for t in qualified}
    bracket = []
    for t1, t2 in r32_matchups:
        if t1 in team_map and t2 in team_map:
            bracket.append([team_map[t1], team_map[t2]])

    return bracket

def play_knockout_round(bracket: List[List[Dict]], rng: random.Random) -> Tuple[List[Dict], List[Dict]]:
    matches = []
    winners = []
    for a, b in bracket:
        match = simulate_knockout_match(a["team"], b["team"], rng)
        matches.append(match)
        winner_team = match["winner"]
        winners.append(next(t for t in (a, b) if t["team"] == winner_team))
    return winners, matches

def simulate_knockout_tournament(qualified: List[Dict], rng: random.Random) -> Dict:
    if len(qualified) != 32:
        return {"rounds": {}, "champion": None, "error": f"Expected 32 qualified teams, got {len(qualified)}"}

    bracket_r32 = build_official_bracket(qualified)

    rounds = {"round_of_32": [], "round_of_16": [], "quarter_finals": [], "semi_finals": [], "third_place": None, "final": None}

    # R32
    winners_r16, rounds["round_of_32"] = play_knockout_round(bracket_r32, rng)

    # Armar llaves de R16 (Ganador Partido 1 vs Ganador Partido 2, etc.)
    bracket_r16 = [ [winners_r16[i], winners_r16[i+1]] for i in range(0, len(winners_r16), 2) ]
    winners_qf, rounds["round_of_16"] = play_knockout_round(bracket_r16, rng)

    bracket_qf = [ [winners_qf[i], winners_qf[i+1]] for i in range(0, len(winners_qf), 2) ]
    winners_sf, rounds["quarter_finals"] = play_knockout_round(bracket_qf, rng)

    bracket_sf = [ [winners_sf[i], winners_sf[i+1]] for i in range(0, len(winners_sf), 2) ]
    finalists, rounds["semi_finals"] = play_knockout_round(bracket_sf, rng)

    # Tercer puesto
    semi_losers = []
    for m in rounds["semi_finals"]:
        loser = m["team_a"] if m["winner"] == m["team_b"] else m["team_b"]
        semi_losers.append(loser)
    if len(semi_losers) == 2:
        rounds["third_place"] = simulate_knockout_match(semi_losers[0], semi_losers[1], rng)

    # Final
    if len(finalists) == 2:
        rounds["final"] = simulate_knockout_match(finalists[0]["team"], finalists[1]["team"], rng)
        champion = rounds["final"]["winner"]
    else:
        champion = None

    return {"rounds": rounds, "champion": champion}


# ============================================================================
# MONTE CARLO ENGINE
# ============================================================================

def run_monte_carlo_simulation(num_simulations: int = DEFAULT_SIMULATIONS, seed: Optional[int] = None) -> Dict:
    num_simulations = max(1, min(int(num_simulations), MAX_SIMULATIONS))
    rng = random.Random(seed)

    group_winners_count = {group: {team: 0 for team in teams} for group, teams in GROUPS.items()}
    group_runners_up_count = {group: {team: 0 for team in teams} for group, teams in GROUPS.items()}
    third_place_count = {group: {team: 0 for team in teams} for group, teams in GROUPS.items()}
    qualified_count = {team: 0 for teams in GROUPS.values() for team in teams}
    finalist_count = {team: 0 for teams in GROUPS.values() for team in teams}
    champion_count = {team: 0 for teams in GROUPS.values() for team in teams}

    last_simulation = None

    for _ in range(num_simulations):
        group_result = simulate_group_stage(GROUPS, rng)

        for group, standings in group_result["standings"].items():
            if len(standings) > 0: group_winners_count[group][standings[0]["team"]] += 1
            if len(standings) > 1: group_runners_up_count[group][standings[1]["team"]] += 1
            if len(standings) > 2: third_place_count[group][standings[2]["team"]] += 1

        for team in group_result["qualified"]:
            qualified_count[team["team"]] += 1

        knockout_result = simulate_knockout_tournament(group_result["qualified"], rng)

        if knockout_result["champion"]:
            champion_count[knockout_result["champion"]] += 1

        final_match = knockout_result["rounds"]["final"]
        if final_match:
            finalist_count[final_match["team_a"]] += 1
            finalist_count[final_match["team_b"]] += 1

        last_simulation = {"group_stage": group_result, "knockout": knockout_result}

    def ratio_map(counter_map: Dict[str, int]) -> Dict[str, float]:
        return {k: round(v / num_simulations, 4) for k, v in counter_map.items()}

    probabilities = {
        "group_winners": {g: ratio_map(v) for g, v in group_winners_count.items()},
        "group_runners_up": {g: ratio_map(v) for g, v in group_runners_up_count.items()},
        "third_place": {g: ratio_map(v) for g, v in third_place_count.items()},
        "qualified": ratio_map(qualified_count),
        "finalist": ratio_map(finalist_count),
        "champion": ratio_map(champion_count),
    }

    return {
        "num_simulations": num_simulations,
        "probabilities": probabilities,
        "last_simulation": last_simulation,
    }

# ============================================================================
# API ENDPOINT
# ============================================================================

@router.get("/simulation/run")
def run_simulation(num_simulations: int = DEFAULT_SIMULATIONS, seed: Optional[int] = None):
    return run_monte_carlo_simulation(num_simulations=num_simulations, seed=seed)
