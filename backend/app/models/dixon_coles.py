import numpy as np
from scipy.stats import poisson
from typing import Tuple, List, Dict

def dixon_coles_probabilities(lambda_home: float, lambda_away: float, max_goals=10, tau=0.04) -> Tuple[Dict[str, float], List[Dict]]:
    prob_matrix = {}
    total_prob = 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = poisson.pmf(i, lambda_home) * poisson.pmf(j, lambda_away)
            if i == 0 and j == 0:
                p *= (1 - lambda_home * lambda_away * tau)
            elif i == 0 and j == 1:
                p *= (1 + lambda_home * tau)
            elif i == 1 and j == 0:
                p *= (1 + lambda_away * tau)
            elif i == 1 and j == 1:
                p *= (1 - tau)
            prob_matrix[(i, j)] = p
            total_prob += p
    for key in prob_matrix:
        prob_matrix[key] /= total_prob
    home_win = sum(p for (i, j), p in prob_matrix.items() if i > j)
    draw = sum(p for (i, j), p in prob_matrix.items() if i == j)
    away_win = sum(p for (i, j), p in prob_matrix.items() if i < j)
    sorted_scores = sorted(prob_matrix.items(), key=lambda x: x[1], reverse=True)[:5]
    top_scores = [{"score": f"{i}-{j}", "probability": round(p, 4)} for (i, j), p in sorted_scores]
    return {
        "home_win": round(home_win, 4),
        "draw": round(draw, 4),
        "away_win": round(away_win, 4)
    }, top_scores

def elo_to_lambda(elo_home: float, elo_away: float, is_host_match: bool = False) -> Tuple[float, float]:
    diff = elo_home - elo_away
    base = 1.20
    home_factor = 1.10 if is_host_match else 1.0
    away_factor = 0.90 if is_host_match else 1.0
    lambda_home = base * home_factor * np.exp(diff / 550)
    lambda_away = base * away_factor * np.exp(-diff / 550)
    return lambda_home, lambda_away
