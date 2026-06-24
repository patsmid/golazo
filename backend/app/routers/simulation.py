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
# CONFIG
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

# En Mundial no hay localía real.
HOSTS = {"Mexico", "Canada", "United States"}
HOME_ADVANTAGE = 0.0


# ============================================================================
# HELPERS
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
    elo_a = get_rating(team_a)
    elo_b = get_rating(team_b)
    lambda_a, lambda_b = elo_to_lambda(elo_a, elo_b, team_a in HOSTS and HOME_ADVANTAGE != 0)
    return (
        clamp(float(lambda_a), 0.20, 3.50),
        clamp(float(lambda_b), 0.20, 3.50),
    )

def fair_play_score(team: dict) -> int:
    # No modelamos tarjetas todavía, así que todos quedan igual.
    return int(team.get("fair_play", 0))


# ============================================================================
# MATCH SIMULATION
# ============================================================================

def simulate_match(team_a: str, team_b: str, rng: random.Random) -> Tuple[int, int]:
    lam_a, lam_b = expected_goals(team_a, team_b)
    goals_a = poisson_sample(lam_a, rng)
    goals_b = poisson_sample(lam_b, rng)
    return goals_a, goals_b

def simulate_group_match(team_a: str, team_b: str, rng: random.Random) -> Dict:
    goals_a, goals_b = simulate_match(team_a, team_b, rng)

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
        "team_a": team_a,
        "team_b": team_b,
        "goals_a": goals_a,
        "goals_b": goals_b,
        "points_a": points_a,
        "points_b": points_b,
        "result_a": result_a,
        "result_b": result_b,
    }

def simulate_knockout_match(team_a: str, team_b: str, rng: random.Random) -> Dict:
    """
    En knockout, si empatan en 90', resolvemos por una probabilidad guiada por Elo.
    Es más estable que una moneda 50/50 y evita campeones absurdos.
    """
    goals_a, goals_b = simulate_match(team_a, team_b, rng)

    if goals_a != goals_b:
        winner = team_a if goals_a > goals_b else team_b
    else:
        elo_a = get_rating(team_a)
        elo_b = get_rating(team_b)
        p_a = 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))
        winner = team_a if rng.random() < p_a else team_b

    return {
        "team_a": team_a,
        "team_b": team_b,
        "goals_a": goals_a,
        "goals_b": goals_b,
        "winner": winner,
    }


# ============================================================================
# FIFA GROUP TIEBREAKERS
# ============================================================================
# Orden usado:
# 1) puntos
# 2) diferencia de goles
# 3) goles a favor
# 4) head-to-head points (solo entre empatados)
# 5) head-to-head goal difference
# 6) head-to-head goals scored
# 7) fair play
# 8) drawing of lots

def _sort_basic(table: List[Dict], rng: random.Random) -> List[Dict]:
    return sorted(
        table,
        key=lambda t: (
            -t["points"],
            -t["gd"],
            -t["gf"],
            -t.get("elo", 1500.0),
            fair_play_score(t),
            rng.random(),  # drawing of lots
        ),
    )

def _head_to_head_subset(team_names: set[str], matches: List[dict]) -> Dict[str, Dict[str, int]]:
    """
    Calcula puntos/gd/gf solo entre equipos empatados.
    """
    stats = {team: {"points": 0, "gf": 0, "ga": 0, "gd": 0} for team in team_names}

    for m in matches:
        a = m["team_a"]
        b = m["team_b"]
        if a not in team_names or b not in team_names:
            continue

        ga = m["goals_a"]
        gb = m["goals_b"]

        stats[a]["gf"] += ga
        stats[a]["ga"] += gb
        stats[b]["gf"] += gb
        stats[b]["ga"] += ga

        if ga > gb:
            stats[a]["points"] += 3
        elif gb > ga:
            stats[b]["points"] += 3
        else:
            stats[a]["points"] += 1
            stats[b]["points"] += 1

    for team in team_names:
        stats[team]["gd"] = stats[team]["gf"] - stats[team]["ga"]

    return stats

def apply_fifa_tiebreakers(group_table: List[Dict], matches: List[dict], rng: random.Random) -> List[Dict]:
    """
    Aplica desempate FIFA a un grupo de 4 equipos.
    """
    if len(group_table) <= 1:
        return group_table

    # Primero orden básico.
    ordered = _sort_basic(group_table, rng)

    # Resolver empates exactos por bloques.
    final_order: List[Dict] = []
    i = 0
    while i < len(ordered):
        j = i + 1
        tied_block = [ordered[i]]

        while j < len(ordered):
            a = ordered[i]
            b = ordered[j]
            same_first_three = (
                a["points"] == b["points"]
                and a["gd"] == b["gd"]
                and a["gf"] == b["gf"]
            )
            if same_first_three:
                tied_block.append(ordered[j])
                j += 1
            else:
                break

        if len(tied_block) == 1:
            final_order.append(tied_block[0])
        else:
            tied_names = {t["team"] for t in tied_block}
            h2h = _head_to_head_subset(tied_names, matches)

            def h2h_key(team: Dict) -> Tuple:
                name = team["team"]
                return (
                    -h2h[name]["points"],
                    -h2h[name]["gd"],
                    -h2h[name]["gf"],
                    fair_play_score(team),
                    rng.random(),
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
        team: {
            "team": team,
            "group": group_letter,
            "points": 0,
            "gf": 0,
            "ga": 0,
            "gd": 0,
            "elo": get_rating(team),
            "fair_play": 0,
            "matches": [],
        }
        for team in teams
    }

    matches: List[dict] = []

    for team_a, team_b in combinations(teams, 2):
        result = simulate_group_match(team_a, team_b, rng)
        matches.append(
            {
                "team_a": team_a,
                "team_b": team_b,
                "goals_a": result["goals_a"],
                "goals_b": result["goals_b"],
            }
        )

        a = stats[team_a]
        b = stats[team_b]

        a["gf"] += result["goals_a"]
        a["ga"] += result["goals_b"]
        a["gd"] = a["gf"] - a["ga"]
        a["points"] += result["points_a"]
        a["matches"].append(
            {
                "opponent": team_b,
                "goals_for": result["goals_a"],
                "goals_against": result["goals_b"],
                "result": result["result_a"],
            }
        )

        b["gf"] += result["goals_b"]
        b["ga"] += result["goals_a"]
        b["gd"] = b["gf"] - b["ga"]
        b["points"] += result["points_b"]
        b["matches"].append(
            {
                "opponent": team_a,
                "goals_for": result["goals_b"],
                "goals_against": result["goals_a"],
                "result": result["result_b"],
            }
        )

    table = list(stats.values())
    table = apply_fifa_tiebreakers(table, matches, rng)
    return table, matches

def simulate_group_stage(groups: Dict[str, List[str]], rng: random.Random) -> Dict:
    standings: Dict[str, List[Dict]] = {}
    group_matches: Dict[str, List[dict]] = {}
    group_winners: List[Dict] = []
    group_runners_up: List[Dict] = []
    third_placed: List[Dict] = []

    for group_letter, teams in groups.items():
        table, matches = build_group_table(group_letter, teams, rng)
        standings[group_letter] = table
        group_matches[group_letter] = matches

        if len(table) > 0:
            group_winners.append({**table[0], "position": 1})
        if len(table) > 1:
            group_runners_up.append({**table[1], "position": 2})
        if len(table) > 2:
            third_placed.append({**table[2], "position": 3})

    best_third = sorted(
        third_placed,
        key=lambda t: (
            -t["points"],
            -t["gd"],
            -t["gf"],
            fair_play_score(t),
            t["elo"] * -1,
        ),
    )[:8]

    qualified = group_winners + group_runners_up + best_third

    return {
        "standings": standings,
        "group_matches": group_matches,
        "group_winners": group_winners,
        "group_runners_up": group_runners_up,
        "third_placed": third_placed,
        "best_third": best_third,
        "qualified": qualified,
    }


# ============================================================================
# KNOCKOUT STAGE
# ============================================================================

def seed_qualified_teams(qualified: List[Dict]) -> List[Dict]:
    """
    Seeding simple y estable.
    winners > runners-up > third-place, luego Elo.
    """
    def seed_bonus(position: int) -> int:
        return {1: 200, 2: 100}.get(position, 0)

    seeded = []
    for t in qualified:
        seeded.append(
            {
                **t,
                "seed_score": float(t.get("elo", 1500.0)) + seed_bonus(int(t.get("position", 3))),
            }
        )

    seeded.sort(key=lambda x: (-x["seed_score"], x["team"]))
    return seeded

def play_knockout_round(teams: List[Dict], rng: random.Random) -> Tuple[List[Dict], List[Dict]]:
    """
    Empareja el mejor con el peor, el segundo con el penúltimo, etc.
    Mucho más simple que un árbol con nodos manuales.
    """
    matches: List[Dict] = []
    winners: List[Dict] = []

    left = 0
    right = len(teams) - 1

    while left < right:
        a = teams[left]
        b = teams[right]

        match = simulate_knockout_match(a["team"], b["team"], rng)
        matches.append(match)

        winner_team = match["winner"]
        winners.append(next(t for t in (a, b) if t["team"] == winner_team))

        left += 1
        right -= 1

    return winners, matches

def simulate_knockout_tournament(qualified: List[Dict], rng: random.Random) -> Dict:
    current = seed_qualified_teams(qualified)

    rounds = {
        "round_of_32": [],
        "round_of_16": [],
        "quarter_finals": [],
        "semi_finals": [],
        "third_place": None,
        "final": None,
    }

    if len(current) != 32:
        return {
            "rounds": rounds,
            "champion": None,
            "error": f"Expected 32 qualified teams, got {len(current)}",
        }

    current, rounds["round_of_32"] = play_knockout_round(current, rng)
    current, rounds["round_of_16"] = play_knockout_round(current, rng)
    current, rounds["quarter_finals"] = play_knockout_round(current, rng)
    current, rounds["semi_finals"] = play_knockout_round(current, rng)

    # Final: last two teams
    if len(current) == 2:
        a, b = current[0], current[1]
        final = simulate_knockout_match(a["team"], b["team"], rng)
        rounds["final"] = final
        champion = final["winner"]

        # Tercer lugar entre los perdedores de semis
        semi_matches = rounds["semi_finals"]
        if len(semi_matches) == 8:
            semi_losers = []
            for m in semi_matches:
                loser = m["team_a"] if m["winner"] == m["team_b"] else m["team_b"]
                semi_losers.append(loser)
            # Si quieres, luego podemos hacer un tercer puesto real.
            rounds["third_place"] = None
    else:
        champion = current[0]["team"] if current else None

    return {
        "rounds": rounds,
        "champion": champion,
    }


# ============================================================================
# MONTE CARLO
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
            if len(standings) > 0:
                group_winners_count[group][standings[0]["team"]] += 1
            if len(standings) > 1:
                group_runners_up_count[group][standings[1]["team"]] += 1
            if len(standings) > 2:
                third_place_count[group][standings[2]["team"]] += 1

        for team in group_result["qualified"]:
            qualified_count[team["team"]] += 1

        knockout_result = simulate_knockout_tournament(group_result["qualified"], rng)
        champion = knockout_result["champion"]
        if champion:
            champion_count[champion] += 1

        final_match = knockout_result["rounds"]["final"]
        if final_match:
            finalist_count[final_match["team_a"]] += 1
            finalist_count[final_match["team_b"]] += 1

        last_simulation = {
            "group_stage": group_result,
            "knockout": knockout_result,
        }

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
# API
# ============================================================================

@router.get("/simulation/run")
def run_simulation(num_simulations: int = DEFAULT_SIMULATIONS, seed: Optional[int] = None):
    return run_monte_carlo_simulation(num_simulations=num_simulations, seed=seed)
