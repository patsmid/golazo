import numpy as np
import math
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


def elo_to_lambda(elo_home, elo_away, is_host=False):
    """
    Convierte diferencias de Elo en parámetros lambda (goles esperados).
    Retorna (lambda_home, lambda_away).
    """
    diff = elo_home - elo_away
    # Aumentamos el home advantage de 0.1 a 0.15
    home_adv = 0.15 if is_host else 0.0
    # Factor base: antes era ~0.9, ahora lo subimos a 1.2
    base_factor = 1.3

    lambda_home = math.exp((diff + home_adv) / 400.0) * base_factor
    lambda_away = math.exp((-diff - home_adv) / 400.0) * base_factor

    # Limitar para evitar valores extremos (mínimo 0.3, máximo 4.5)
    lambda_home = max(0.3, min(4.5, lambda_home))
    lambda_away = max(0.3, min(4.5, lambda_away))

    return lambda_home, lambda_away
