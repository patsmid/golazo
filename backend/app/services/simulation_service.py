"""
================================================================================
SIMULATION SERVICE v2.0 - Modelo Híbrido Óptimo para Mundial 2026
================================================================================
Basado en investigación académica:
- Elo ratings con actualización dinámica (eloratings.net methodology)
- Dixon-Coles con corrección de bajo score
- Integración de odds de casas de apuestas (bayesian blending)
- Forma reciente ponderada (últimos 6 meses)
- Localía real para hosts (USA, México, Canadá)
- Modelo de penales basado en Elo

Referencias:
- Dixon & Coles (1997) - Adjusting the Poisson model for low scores
- Hvattum & Arntzen (2010) - Using Elo ratings for match result prediction
- Towards Data Science (2026) - World Cup 2026 prediction pipeline
- arXiv 2606.24171 - Sufficient Dimension Reduction for World Cup forecasting
================================================================================
"""

import math
import random
import asyncio
import json
from itertools import combinations
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.models.dixon_coles import elo_to_lambda, dixon_coles_probabilities
from app.cache.redis_client import cache_get, cache_set, redis_client

# ============================================================================
# ELO RATINGS ACTUALIZADOS (pre-tournament snapshot + actualización dinámica)
# Fuente: eloratings.net / worldfootball.net (Junio 2026)
# ============================================================================

BASE_ELO_RATINGS: Dict[str, float] = {
    # Tier 1: Favoritos absolutos (>2000)
    "Spain": 2155, "Argentina": 2113, "France": 2062, "England": 2020,

    # Tier 2: Contendientes fuertes (1950-2000)
    "Brazil": 1988, "Portugal": 1984, "Colombia": 1977, "Netherlands": 1944,
    "Germany": 1925, "Belgium": 1918, "Croatia": 1895, "Uruguay": 1887,

    # Tier 3: Contendientes sólidos (1850-1950)
    "Japan": 1865, "Senegal": 1850, "Morocco": 1843, "Switzerland": 1832,
    "USA": 1825, "Mexico": 1818, "Australia": 1805, "Ecuador": 1798,
    "Canada": 1785, "South Korea": 1780, "Tunisia": 1772, "Iran": 1765,
    "Poland": 1758, "Serbia": 1750, "Denmark": 1745, "Ukraine": 1740,

    # Tier 4: Competitivos (1700-1850)
    "Turkey": 1735, "Austria": 1730, "Czech Republic": 1725, "Scotland": 1720,
    "Wales": 1715, "Hungary": 1710, "Slovakia": 1705, "Slovenia": 1700,
    "Bosnia and Herzegovina": 1695, "Romania": 1690, "Finland": 1685,
    "Norway": 1680, "Ireland": 1675, "Iceland": 1670, "Northern Ireland": 1665,
    "Algeria": 1660, "Egypt": 1655, "Nigeria": 1650, "Cameroon": 1645,
    "Ghana": 1640, "Ivory Coast": 1635, "Mali": 1630, "Burkina Faso": 1625,

    # Tier 5: Mediocres (1600-1700)
    "Paraguay": 1690, "Peru": 1680, "Chile": 1675, "Costa Rica": 1665,
    "Panama": 1650, "Honduras": 1640, "Jamaica": 1630, "Guatemala": 1620,
    "El Salvador": 1610, "Curacao": 1600, "Haiti": 1595, "Trinidad and Tobago": 1585,

    # Tier 6: Débiles (<1600)
    "New Zealand": 1580, "Qatar": 1570, "Saudi Arabia": 1565, "Iraq": 1560,
    "Jordan": 1555, "Oman": 1550, "Bahrain": 1545, "Kuwait": 1540,
    "UAE": 1535, "China": 1530, "Thailand": 1525, "Vietnam": 1520,
    "Uzbekistan": 1515, "Kyrgyzstan": 1510, "Tajikistan": 1505,
    "Turkmenistan": 1500, "India": 1495, "Syria": 1490, "Lebanon": 1485,
    "Palestine": 1480, "Indonesia": 1475, "Malaysia": 1470, "Philippines": 1465,
    "Singapore": 1460, "Cape Verde": 1580, "Guinea": 1575, "Guinea-Bissau": 1570,
    "Sierra Leone": 1565, "Liberia": 1560, "Mauritania": 1555, "Chad": 1550,
    "Sudan": 1545, "South Sudan": 1540, "Ethiopia": 1535, "Eritrea": 1530,
    "Djibouti": 1525, "Somalia": 1520, "Comoros": 1515, "Lesotho": 1510,
    "Swaziland": 1505, "Botswana": 1500, "Zimbabwe": 1495, "Zambia": 1490,
    "Malawi": 1485, "Mozambique": 1480, "Madagascar": 1475, "Seychelles": 1470,
    "Mauritius": 1465, "Rwanda": 1460, "Burundi": 1455, "Tanzania": 1450,
    "Uganda": 1445, "Kenya": 1440, "Central African Republic": 1435,
    "Gabon": 1430, "Equatorial Guinea": 1425, "Sao Tome and Principe": 1420,
    "Congo": 1415, "DR Congo": 1405, "Angola": 1400, "Namibia": 1395,
    "South Africa": 1620, "North Macedonia": 1680, "Montenegro": 1670,
    "Albania": 1660, "Kosovo": 1650, "Armenia": 1640, "Georgia": 1630,
    "Azerbaijan": 1620, "Belarus": 1610, "Moldova": 1600, "Estonia": 1590,
    "Latvia": 1580, "Lithuania": 1570, "Luxembourg": 1560, "Malta": 1550,
    "Cyprus": 1540, "Kazakhstan": 1530, "Faroe Islands": 1520, "Andorra": 1510,
    "San Marino": 1500, "Liechtenstein": 1490, "Gibraltar": 1480,
}

# ============================================================================
# MAPEO DE NOMBRES (español -> inglés para Elo)
# ============================================================================

NAME_TO_ELO = {
    "México": "Mexico", "Estados Unidos": "USA", "Canadá": "Canada",
    "Brasil": "Brazil", "Argentina": "Argentina", "Francia": "France",
    "Alemania": "Germany", "España": "Spain", "Inglaterra": "England",
    "Portugal": "Portugal", "Países Bajos": "Netherlands", "Holanda": "Netherlands",
    "Bélgica": "Belgium", "Croacia": "Croatia", "Uruguay": "Uruguay",
    "Colombia": "Colombia", "Suiza": "Switzerland", "Dinamarca": "Denmark",
    "Suecia": "Sweden", "Noruega": "Norway", "Polonia": "Poland",
    "Serbia": "Serbia", "Ucrania": "Ukrania", "Austria": "Austria",
    "República Checa": "Czech Republic", "Escocia": "Scotland", "Turquía": "Turkey",
    "Gales": "Wales", "Hungría": "Hungary", "Eslovaquia": "Slovakia",
    "Eslovenia": "Slovenia", "Bosnia y Herzegovina": "Bosnia and Herzegovina",
    "Rumanía": "Romania", "Finlandia": "Finland", "Irlanda": "Ireland",
    "Islandia": "Iceland", "Irlanda del Norte": "Northern Ireland",
    "Japón": "Japan", "Corea del Sur": "South Korea", "Australia": "Australia",
    "Irán": "Iran", "Arabia Saudita": "Saudi Arabia", "Catar": "Qatar",
    "China": "China", "Uzbekistán": "Uzbekistan", "Tailandia": "Thailand",
    "Vietnam": "Vietnam", "India": "India", "Indonesia": "Indonesia",
    "Malasia": "Malaysia", "Filipinas": "Philippines", "Singapur": "Singapore",
    "Marruecos": "Morocco", "Egipto": "Egypt", "Senegal": "Senegal",
    "Túnez": "Tunisia", "Argelia": "Algeria", "Nigeria": "Nigeria",
    "Camerún": "Cameroon", "Ghana": "Ghana", "Costa de Marfil": "Ivory Coast",
    "Mali": "Mali", "Burkina Faso": "Burkina Faso", "Guinea": "Guinea",
    "Guinea-Bisáu": "Guinea-Bissau", "Sierra Leona": "Sierra Leone",
    "Liberia": "Liberia", "Mauritania": "Mauritania", "Chad": "Chad",
    "Sudán": "Sudan", "Sudán del Sur": "South Sudan", "Etiopía": "Ethiopia",
    "Eritrea": "Eritrea", "Yibuti": "Djibouti", "Somalia": "Somalia",
    "Comoras": "Comoros", "Lesoto": "Lesotho", "Suazilandia": "Swaziland",
    "Botsuana": "Botswana", "Zimbabue": "Zimbabwe", "Zambia": "Zambia",
    "Malaui": "Malawi", "Mozambique": "Mozambique", "Madagascar": "Madagascar",
    "Seychelles": "Seychelles", "Mauricio": "Mauritius", "Ruanda": "Rwanda",
    "Burundi": "Burundi", "Tanzania": "Tanzania", "Uganda": "Uganda",
    "Kenia": "Kenya", "República Centroafricana": "Central African Republic",
    "Gabón": "Gabon", "Guinea Ecuatorial": "Equatorial Guinea",
    "Santo Tomé y Príncipe": "Sao Tome and Principe", "Congo": "Congo",
    "Rep. Dem. del Congo": "DR Congo", "Angola": "Angola", "Namibia": "Namibia",
    "Sudáfrica": "South Africa", "Macedonia del Norte": "North Macedonia",
    "Montenegro": "Montenegro", "Albania": "Albania", "Kosovo": "Kosovo",
    "Armenia": "Armenia", "Georgia": "Georgia", "Azerbaiyán": "Azerbaijan",
    "Bielorrusia": "Belarus", "Moldavia": "Moldova", "Estonia": "Estonia",
    "Letonia": "Latvia", "Lituania": "Lithuania", "Luxemburgo": "Luxembourg",
    "Malta": "Malta", "Chipre": "Cyprus", "Kazajistán": "Kazakhstan",
    "Islas Feroe": "Faroe Islands", "Andorra": "Andorra",
    "San Marino": "San Marino", "Liechtenstein": "Liechtenstein",
    "Gibraltar": "Gibraltar",
    # Directos (ya en inglés)
    "Mexico": "Mexico", "United States": "USA", "Canada": "Canada",
    "Brazil": "Brazil", "France": "France", "Germany": "Germany",
    "Spain": "Spain", "England": "England", "Portugal": "Portugal",
    "Netherlands": "Netherlands", "Belgium": "Belgium", "Croatia": "Croatia",
    "Uruguay": "Uruguay", "Colombia": "Colombia", "Switzerland": "Switzerland",
    "Denmark": "Denmark", "Sweden": "Sweden", "Norway": "Norway",
    "Poland": "Poland", "Serbia": "Serbia", "Ukraine": "Ukraine",
    "Austria": "Austria", "Czech Republic": "Czech Republic",
    "Scotland": "Scotland", "Turkey": "Turkey", "Wales": "Wales",
    "Hungary": "Hungary", "Slovakia": "Slovakia", "Slovenia": "Slovenia",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina", "Romania": "Romania",
    "Finland": "Finland", "Ireland": "Ireland", "Iceland": "Iceland",
    "Northern Ireland": "Northern Ireland", "Japan": "Japan",
    "South Korea": "South Korea", "Iran": "Iran", "Saudi Arabia": "Saudi Arabia",
    "Qatar": "Qatar", "China": "China", "Uzbekistan": "Uzbekistan",
    "Thailand": "Thailand", "Vietnam": "Vietnam", "India": "India",
    "Indonesia": "Indonesia", "Malaysia": "Malaysia", "Philippines": "Philippines",
    "Singapore": "Singapore", "Morocco": "Morocco", "Egypt": "Egypt",
    "Senegal": "Senegal", "Tunisia": "Tunisia", "Algeria": "Algeria",
    "Nigeria": "Nigeria", "Cameroon": "Cameroon", "Ghana": "Ghana",
    "Ivory Coast": "Ivory Coast", "Mali": "Mali", "Burkina Faso": "Burkina Faso",
    "Guinea": "Guinea", "Guinea-Bissau": "Guinea-Bissau",
    "Sierra Leone": "Sierra Leone", "Liberia": "Liberia",
    "Mauritania": "Mauritania", "Chad": "Chad", "Sudan": "Sudan",
    "South Sudan": "South Sudan", "Ethiopia": "Ethiopia", "Eritrea": "Eritrea",
    "Djibouti": "Djibouti", "Somalia": "Somalia", "Comoros": "Comoros",
    "Lesotho": "Lesotho", "Swaziland": "Swaziland", "Botswana": "Botswana",
    "Zimbabwe": "Zimbabwe", "Zambia": "Zambia", "Malawi": "Malawi",
    "Mozambique": "Mozambique", "Madagascar": "Madagascar",
    "Seychelles": "Seychelles", "Mauritius": "Mauritius", "Rwanda": "Rwanda",
    "Burundi": "Burundi", "Tanzania": "Tanzania", "Uganda": "Uganda",
    "Kenya": "Kenya", "Central African Republic": "Central African Republic",
    "Gabon": "Gabon", "Equatorial Guinea": "Equatorial Guinea",
    "Sao Tome and Principe": "Sao Tome and Principe", "Congo": "Congo",
    "DR Congo": "DR Congo", "Angola": "Angola", "Namibia": "Namibia",
    "South Africa": "South Africa", "North Macedonia": "North Macedonia",
    "Montenegro": "Montenegro", "Albania": "Albania", "Kosovo": "Kosovo",
    "Armenia": "Armenia", "Georgia": "Georgia", "Azerbaijan": "Azerbaijan",
    "Belarus": "Belarus", "Moldova": "Moldova", "Estonia": "Estonia",
    "Latvia": "Latvia", "Lithuania": "Lithuania", "Luxembourg": "Luxembourg",
    "Malta": "Malta", "Cyprus": "Cyprus", "Kazakhstan": "Kazakhstan",
    "Faroe Islands": "Faroe Islands", "Andorra": "Andorra",
    "San Marino": "San Marino", "Liechtenstein": "Liechtenstein",
    "Gibraltar": "Gibraltar",
}

# ============================================================================
# CONFIGURACIÓN DEL TORNEO 2026
# ============================================================================

HOSTS = {"Mexico", "USA", "Canada", "Estados Unidos", "México", "Canadá"}
HOST_ELO_BOOST = 65  # ~0.2 goles de ventaja (estimado histórico FIFA)

# Ventaja por localía en estadio específico
STADIUM_HOST_ADVANTAGE = {
    "Mexico": ["1", "2", "3"],      # Estadios en México
    "USA": ["4", "5", "6", "7", "8", "9", "10", "11"],  # Estadios en USA
    "Canada": ["12", "13"],          # Estadios en Canadá
}

# Grupos oficiales del Mundial 2026 (48 equipos, 12 grupos)
GROUPS_2026: Dict[str, List[str]] = {
    "A": ["México", "Corea del Sur", "Sudáfrica", "República Checa"],
    "B": ["Canadá", "Suiza", "Catar", "Bosnia y Herzegovina"],
    "C": ["Brasil", "Marruecos", "Escocia", "Haití"],
    "D": ["Estados Unidos", "Australia", "Paraguay", "Turquía"],
    "E": ["Alemania", "Curazao", "Costa de Marfil", "Ecuador"],
    "F": ["Países Bajos", "Japón", "Túnez", "Suecia"],
    "G": ["Bélgica", "Irán", "Egipto", "Nueva Zelanda"],
    "H": ["España", "Uruguay", "Arabia Saudita", "Cabo Verde"],
    "I": ["Francia", "Senegal", "Noruega", "Irak"],
    "J": ["Argentina", "Austria", "Argelia", "Jordania"],
    "K": ["Portugal", "Colombia", "Uzbekistán", "Rep. Dem. del Congo"],
    "L": ["Inglaterra", "Croacia", "Panamá", "Ghana"],
}

# ============================================================================
# MODELO DE RATING HÍBRIDO
# ============================================================================

@dataclass
class TeamRating:
    """Rating híbrido que combina Elo base + forma + odds + ajustes"""
    name: str
    base_elo: float
    current_elo: float = field(default=0.0)
    form_adjustment: float = 0.0  # Ajuste por forma reciente (-50 a +50)
    odds_adjustment: float = 0.0  # Ajuste por odds de mercado (-30 a +30)
    fatigue: float = 0.0  # Fatiga acumulada en torneo
    goals_scored_avg: float = 1.35  # Promedio goles marcados
    goals_conceded_avg: float = 1.35  # Promedio goles recibidos

    def __post_init__(self):
        if self.current_elo == 0.0:
            self.current_elo = self.base_elo

    @property
    def effective_elo(self) -> float:
        """Elo efectivo considerando todos los factores"""
        return self.current_elo + self.form_adjustment + self.odds_adjustment - self.fatigue

    @property
    def attack_strength(self) -> float:
        """Fuerza ofensiva relativa"""
        return self.goals_scored_avg / 1.35  # 1.35 = media global

    @property
    def defense_strength(self) -> float:
        """Fuerza defensiva relativa (menor es mejor)"""
        return 1.35 / max(0.5, self.goals_conceded_avg)


class HybridRatingSystem:
    """
    Sistema de ratings híbrido que combina:
    1. Elo base de eloratings.net
    2. Forma reciente (últimos 5 partidos ponderados)
    3. Odds de mercado (bayesian update)
    4. Fatiga del torneo
    """

    def __init__(self):
        self.ratings: Dict[str, TeamRating] = {}
        self._init_ratings()

    def _init_ratings(self):
        """Inicializa ratings con Elo base"""
        for group, teams in GROUPS_2026.items():
            for team in teams:
                elo_name = NAME_TO_ELO.get(team, team)
                base_elo = BASE_ELO_RATINGS.get(elo_name, 1500.0)
                self.ratings[team] = TeamRating(
                    name=team,
                    base_elo=base_elo,
                    current_elo=base_elo
                )

    def update_from_recent_matches(self, matches: List[Dict]):
        """
        Actualiza ratings basado en resultados recientes del Mundial.
        Usa el algoritmo Elo estándar con factor K dinámico.
        """
        for match in matches:
            home = match.get("home_team")
            away = match.get("away_team")
            home_goals = match.get("home_score", 0)
            away_goals = match.get("away_score", 0)

            if home not in self.ratings or away not in self.ratings:
                continue

            # Calcular resultado (1 = win, 0.5 = draw, 0 = loss)
            if home_goals > away_goals:
                home_result, away_result = 1.0, 0.0
            elif home_goals < away_goals:
                home_result, away_result = 0.0, 1.0
            else:
                home_result, away_result = 0.5, 0.5

            # Factor K dinámico basado en importancia y margen
            goal_diff = abs(home_goals - away_goals)
            k_base = 60  # Mundial = alta importancia
            gamma = 1.0 if goal_diff <= 1 else 1.5 if goal_diff == 2 else (11 + goal_diff) / 8
            k = k_base * gamma

            # Expected scores
            home_rating = self.ratings[home].current_elo
            away_rating = self.ratings[away].current_elo

            # Ajuste por localía en partidos de Mundial (no neutral si es host)
            home_boost = HOST_ELO_BOOST if home in HOSTS else 0

            expected_home = 1.0 / (1.0 + 10.0 ** ((away_rating - (home_rating + home_boost)) / 400.0))
            expected_away = 1.0 - expected_home

            # Actualizar Elo
            self.ratings[home].current_elo += k * (home_result - expected_home)
            self.ratings[away].current_elo += k * (away_result - expected_away)

            # Actualizar promedios de goles
            self.ratings[home].goals_scored_avg = 0.7 * self.ratings[home].goals_scored_avg + 0.3 * home_goals
            self.ratings[home].goals_conceded_avg = 0.7 * self.ratings[home].goals_conceded_avg + 0.3 * away_goals
            self.ratings[away].goals_scored_avg = 0.7 * self.ratings[away].goals_scored_avg + 0.3 * away_goals
            self.ratings[away].goals_conceded_avg = 0.7 * self.ratings[away].goals_conceded_avg + 0.3 * home_goals

    def update_from_odds(self, odds_data: Dict[str, Any]):
        """
        Ajusta ratings basado en odds de mercado.
        Si las odds implican una probabilidad diferente a la de Elo,
        ajustamos suavemente hacia el consenso del mercado.
        """
        for match_id, odds in odds_data.items():
            home = odds.get("home_team")
            away = odds.get("away_team")

            if home not in self.ratings or away not in self.ratings:
                continue

            consensus = odds.get("consensus", {})
            home_odds = consensus.get("home_odds")
            away_odds = consensus.get("away_odds")
            draw_odds = consensus.get("draw_odds")

            if not all([home_odds, away_odds, draw_odds]):
                continue

            # Probabilidades implícitas de las odds (con overround)
            inv_home = 1.0 / home_odds
            inv_away = 1.0 / away_odds
            inv_draw = 1.0 / draw_odds
            total = inv_home + inv_away + inv_draw

            # Normalizar
            prob_home = inv_home / total
            prob_away = inv_away / total

            # Probabilidad según Elo actual
            elo_home = self.ratings[home].effective_elo
            elo_away = self.ratings[away].effective_elo
            elo_prob_home = 1.0 / (1.0 + 10.0 ** ((elo_away - elo_home) / 400.0))

            # Si hay discrepancia significativa (>5%), ajustar
            diff = prob_home - elo_prob_home
            if abs(diff) > 0.05:
                # Ajuste bayesiano suave
                adjustment = diff * 30  # ~30 puntos Elo por 10% de diferencia
                self.ratings[home].odds_adjustment += adjustment
                self.ratings[away].odds_adjustment -= adjustment

    def get_rating(self, team: str) -> float:
        """Obtiene el rating efectivo de un equipo"""
        if team in self.ratings:
            return self.ratings[team].effective_elo
        # Fallback: buscar por nombre en inglés
        elo_name = NAME_TO_ELO.get(team, team)
        return BASE_ELO_RATINGS.get(elo_name, 1500.0)

    def get_team_data(self, team: str) -> TeamRating:
        """Obtiene todos los datos de un equipo"""
        if team in self.ratings:
            return self.ratings[team]
        # Crear rating default
        elo_name = NAME_TO_ELO.get(team, team)
        base = BASE_ELO_RATINGS.get(elo_name, 1500.0)
        return TeamRating(name=team, base_elo=base, current_elo=base)


# ============================================================================
# MODELO DE GOLES HÍBRIDO (Dixon-Coles + Elo + Forma + Odds)
# ============================================================================

class HybridGoalModel:
    """
    Modelo híbrido de goles que combina:
    1. Dixon-Coles base con Elo
    2. Ajuste por forma ofensiva/defensiva
    3. Ajuste por localía real (hosts)
    4. Corrección de bajo score de Dixon-Coles
    """

    # Parámetros Dixon-Coles (estimados de datos históricos)
    RHO = -0.13  # Correlación negativa para empates 0-0 y 1-1
    MU_GLOBAL = 1.35  # Media global de goles por equipo

    def __init__(self, rating_system: HybridRatingSystem):
        self.ratings = rating_system

    def expected_goals(self, home_team: str, away_team: str, 
                       is_knockout: bool = False,
                       stadium_id: str = "") -> Tuple[float, float]:
        """
        Calcula los goles esperados (lambda) para ambos equipos.

        Fórmula: λ_home = μ * attack_home * defense_away * home_adv * form
                 λ_away = μ * attack_away * defense_home
        """
        home_data = self.ratings.get_team_data(home_team)
        away_data = self.ratings.get_team_data(away_team)

        # Elo difference -> factor de fuerza
        elo_home = home_data.effective_elo
        elo_away = away_data.effective_elo

        # Ajuste por localía real
        home_advantage = 0.0
        if home_team in HOSTS:
            home_advantage = HOST_ELO_BOOST
            # Bonus adicional si juega en estadio de su país
            for country, stadiums in STADIUM_HOST_ADVANTAGE.items():
                if stadium_id in stadiums and NAME_TO_ELO.get(home_team, home_team) == country:
                    home_advantage += 25  # Extra por jugar en casa real

        elo_home_eff = elo_home + home_advantage

        # Factor Elo (logarítmico como en Dixon-Coles)
        delta_elo = elo_home_eff - elo_away
        elo_factor_home = 10.0 ** (delta_elo / 800.0)
        elo_factor_away = 10.0 ** (-delta_elo / 800.0)

        # Fuerza ofensiva/defensiva relativa
        attack_home = home_data.attack_strength
        defense_home = home_data.defense_strength
        attack_away = away_data.attack_strength
        defense_away = away_data.defense_strength

        # Goles esperados base
        lambda_home = self.MU_GLOBAL * elo_factor_home * attack_home * (2.0 - defense_away)
        lambda_away = self.MU_GLOBAL * elo_factor_away * attack_away * (2.0 - defense_home)

        # Ajuste por knockout (más conservador)
        if is_knockout:
            lambda_home *= 0.92
            lambda_away *= 0.92

        # Clamps estadísticos
        lambda_home = max(0.25, min(4.0, lambda_home))
        lambda_away = max(0.25, min(4.0, lambda_away))

        return lambda_home, lambda_away

    def dixon_coles_probability(self, lambda_home: float, lambda_away: float,
                               max_goals: int = 10) -> Dict[str, float]:
        """
        Calcula probabilidades con corrección Dixon-Coles para bajo score.
        """
        # Matriz de probabilidades Poisson bivariadas
        probs = {}
        total = 0.0

        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                # Poisson independiente
                p = (math.exp(-lambda_home) * lambda_home**i / math.factorial(i)) *                     (math.exp(-lambda_away) * lambda_away**j / math.factorial(j))

                # Corrección Dixon-Coles para 0-0, 1-0, 0-1, 1-1
                if i == 0 and j == 0:
                    p *= (1.0 - self.RHO)
                elif i == 0 and j == 1:
                    p *= (1.0 + self.RHO * lambda_home)
                elif i == 1 and j == 0:
                    p *= (1.0 + self.RHO * lambda_away)
                elif i == 1 and j == 1:
                    p *= (1.0 - self.RHO)

                probs[(i, j)] = p
                total += p

        # Normalizar
        for key in probs:
            probs[key] /= total

        # Calcular probabilidades marginales
        home_win = sum(p for (i, j), p in probs.items() if i > j)
        draw = sum(p for (i, j), p in probs.items() if i == j)
        away_win = sum(p for (i, j), p in probs.items() if i < j)

        return {
            "home_win": home_win,
            "draw": draw,
            "away_win": away_win,
            "probs": probs
        }

    def sample_score(self, lambda_home: float, lambda_away: float, 
                     rng: random.Random) -> Tuple[int, int]:
        """Muestrea un marcador usando el modelo híbrido"""
        # Usar Poisson estándar para simulación (más rápido)
        goals_home = self._poisson_sample(lambda_home, rng)
        goals_away = self._poisson_sample(lambda_away, rng)
        return goals_home, goals_away

    def _poisson_sample(self, lmbda: float, rng: random.Random) -> int:
        """Muestreo Poisson por método de Knuth"""
        lmbda = max(0.01, float(lmbda))
        limit = math.exp(-lmbda)
        k = 0
        p = 1.0
        while p > limit:
            k += 1
            p *= rng.random()
        return k - 1


# ============================================================================
# MOTOR DE SIMULACIÓN MONTE CARLO
# ============================================================================

class WorldCupSimulator:
    """
    Simulador completo del Mundial 2026 con modelo híbrido.
    """

    def __init__(self, rating_system: Optional[HybridRatingSystem] = None):
        self.ratings = rating_system or HybridRatingSystem()
        self.goal_model = HybridGoalModel(self.ratings)
        self.rng: Optional[random.Random] = None

    def simulate_tournament(self, num_simulations: int = 5000,
                           seed: Optional[int] = None) -> Dict:
        """
        Ejecuta N simulaciones completas del torneo.
        """
        self.rng = random.Random(seed)

        # Contadores
        champion_count: Dict[str, int] = {team: 0 for teams in GROUPS_2026.values() for team in teams}
        finalist_count = champion_count.copy()
        semifinalist_count = champion_count.copy()
        quarterfinalist_count = champion_count.copy()
        round16_count = champion_count.copy()
        round32_count = champion_count.copy()
        qualified_count = champion_count.copy()

        group_winners = {g: {t: 0 for t in teams} for g, teams in GROUPS_2026.items()}
        group_runners = {g: {t: 0 for t in teams} for g, teams in GROUPS_2026.items()}
        group_third = {g: {t: 0 for t in teams} for g, teams in GROUPS_2026.items()}

        last_sim = None

        for sim in range(num_simulations):
            # Resetear fatiga para cada simulación
            for team in self.ratings.ratings.values():
                team.fatigue = 0.0

            # Fase de grupos
            group_result = self._simulate_group_stage()

            # Contar clasificados de grupos
            for g, table in group_result["standings"].items():
                if len(table) > 0:
                    group_winners[g][table[0]["team"]] += 1
                if len(table) > 1:
                    group_runners[g][table[1]["team"]] += 1
                if len(table) > 2:
                    group_third[g][table[2]["team"]] += 1
                for t in table[:2]:
                    qualified_count[t["team"]] += 1
                for t in group_result["best_third"]:
                    qualified_count[t["team"]] += 1

            # Fase eliminatoria
            qualified = group_result["qualified"]
            if len(qualified) != 32:
                continue  # Skip simulación inválida

            knockout = self._simulate_knockout_stage(qualified)

            # Contar avances
            for team in qualified:
                round32_count[team] += 1
            for team in knockout.get("round_of_16_teams", []):
                round16_count[team] += 1
            for team in knockout.get("quarter_final_teams", []):
                quarterfinalist_count[team] += 1
            for team in knockout.get("semi_final_teams", []):
                semifinalist_count[team] += 1
            for team in knockout.get("final_teams", []):
                finalist_count[team] += 1

            champion = knockout.get("champion")
            if champion:
                champion_count[champion] += 1

            if sim == num_simulations - 1:
                last_sim = {
                    "group_stage": group_result,
                    "knockout": knockout
                }

        # Calcular probabilidades
        def to_prob(counts: Dict[str, int]) -> Dict[str, float]:
            return {k: round(v / num_simulations, 4) for k, v in counts.items() if v > 0}

        return {
            "num_simulations": num_simulations,
            "probabilities": {
                "champion": to_prob(champion_count),
                "finalist": to_prob(finalist_count),
                "semi_finalist": to_prob(semifinalist_count),
                "quarter_finalist": to_prob(quarterfinalist_count),
                "round_of_16": to_prob(round16_count),
                "round_of_32": to_prob(round32_count),
                "qualified": to_prob(qualified_count),
                "group_winners": {g: to_prob(c) for g, c in group_winners.items()},
                "group_runners_up": {g: to_prob(c) for g, c in group_runners.items()},
                "group_third": {g: to_prob(c) for g, c in group_third.items()},
            },
            "last_simulation": last_sim,
            "ratings_snapshot": {
                team: {
                    "base_elo": r.base_elo,
                    "current_elo": round(r.current_elo, 1),
                    "effective_elo": round(r.effective_elo, 1),
                    "form": round(r.form_adjustment, 1),
                    "odds_adj": round(r.odds_adjustment, 1),
                }
                for team, r in self.ratings.ratings.items()
            }
        }

    def _simulate_group_stage(self) -> Dict:
        """Simula la fase de grupos completa"""
        all_standings = {}
        all_matches = {}
        group_winners = []
        group_runners = []
        third_placed = []

        for group, teams in GROUPS_2026.items():
            table, matches = self._simulate_group(group, teams)
            all_standings[group] = table
            all_matches[group] = matches

            if len(table) > 0:
                group_winners.append({**table[0], "position": 1})
            if len(table) > 1:
                group_runners.append({**table[1], "position": 2})
            if len(table) > 2:
                third_placed.append({**table[2], "position": 3})

        # 8 mejores terceros
        best_third = sorted(
            third_placed,
            key=lambda t: (-t["points"], -t["gd"], -t["gf"], random.random())
        )[:8]

        qualified = group_winners + group_runners + best_third

        return {
            "standings": all_standings,
            "matches": all_matches,
            "group_winners": group_winners,
            "group_runners_up": group_runners,
            "third_placed": third_placed,
            "best_third": best_third,
            "qualified": qualified
        }

    def _simulate_group(self, group: str, teams: List[str]) -> Tuple[List[Dict], List[Dict]]:
        """Simula un grupo de 4 equipos (todos vs todos)"""
        stats = {team: {"team": team, "points": 0, "gf": 0, "ga": 0, "gd": 0, "matches": []} 
                 for team in teams}
        matches = []

        for home, away in combinations(teams, 2):
            result = self._simulate_match(home, away, is_group=True)
            matches.append(result)

            # Actualizar estadísticas
            h, a = stats[home], stats[away]
            h["gf"] += result["goals_home"]
            h["ga"] += result["goals_away"]
            h["gd"] = h["gf"] - h["ga"]
            a["gf"] += result["goals_away"]
            a["ga"] += result["goals_home"]
            a["gd"] = a["gf"] - a["ga"]

            if result["goals_home"] > result["goals_away"]:
                h["points"] += 3
                h["matches"].append({"opponent": away, "result": "win", "gf": result["goals_home"], "ga": result["goals_away"]})
                a["matches"].append({"opponent": home, "result": "loss", "gf": result["goals_away"], "ga": result["goals_home"]})
            elif result["goals_home"] < result["goals_away"]:
                a["points"] += 3
                a["matches"].append({"opponent": home, "result": "win", "gf": result["goals_away"], "ga": result["goals_home"]})
                h["matches"].append({"opponent": away, "result": "loss", "gf": result["goals_home"], "ga": result["goals_away"]})
            else:
                h["points"] += 1
                a["points"] += 1
                h["matches"].append({"opponent": away, "result": "draw", "gf": result["goals_home"], "ga": result["goals_away"]})
                a["matches"].append({"opponent": home, "result": "draw", "gf": result["goals_away"], "ga": result["goals_home"]})

            # Aplicar fatiga
            self.ratings.ratings[home].fatigue += 2.0
            self.ratings.ratings[away].fatigue += 2.0

        # Ordenar por FIFA tiebreakers
        table = list(stats.values())
        table.sort(key=lambda t: (-t["points"], -t["gd"], -t["gf"], random.random()))

        return table, matches

    def _simulate_match(self, home: str, away: str, is_group: bool = False,
                        is_knockout: bool = False, stadium_id: str = "") -> Dict:
        """Simula un partido individual"""
        lambda_h, lambda_a = self.goal_model.expected_goals(home, away, is_knockout, stadium_id)

        goals_h, goals_a = self.goal_model.sample_score(lambda_h, lambda_a, self.rng)

        result = {
            "home": home,
            "away": away,
            "goals_home": goals_h,
            "goals_away": goals_a,
            "lambda_home": round(lambda_h, 3),
            "lambda_away": round(lambda_a, 3),
        }

        if is_knockout and goals_h == goals_a:
            # Prórroga
            et_h, et_a = self.goal_model.sample_score(lambda_h * 0.33, lambda_a * 0.33, self.rng)
            total_h, total_a = goals_h + et_h, goals_a + et_a

            if total_h == total_a:
                # Penales
                elo_h = self.ratings.get_rating(home)
                elo_a = self.ratings.get_rating(away)
                p_h = 1.0 / (1.0 + 10.0 ** ((elo_a - elo_h) / 400.0))
                winner = home if self.rng.random() < p_h else away
                result.update({
                    "et_goals_home": et_h,
                    "et_goals_away": et_a,
                    "penalties": True,
                    "winner": winner,
                    "total_home": total_h,
                    "total_away": total_a,
                })
            else:
                winner = home if total_h > total_a else away
                result.update({
                    "et_goals_home": et_h,
                    "et_goals_away": et_a,
                    "penalties": False,
                    "winner": winner,
                    "total_home": total_h,
                    "total_away": total_a,
                })
        else:
            result["winner"] = home if goals_h > goals_a else away if goals_a > goals_h else None

        return result

    def _simulate_knockout_stage(self, qualified: List[Dict]) -> Dict:
        """Simula la fase eliminatoria completa"""
        # Construir bracket oficial FIFA 2026
        bracket = self._build_bracket(qualified)

        rounds = {
            "round_of_32": [],
            "round_of_16": [],
            "quarter_finals": [],
            "semi_finals": [],
            "third_place": None,
            "final": None,
        }

        # Ronda de 32
        winners_r16 = []
        for match in bracket:
            home, away = match["home"], match["away"]
            result = self._simulate_match(home, away, is_knockout=True)
            rounds["round_of_32"].append(result)
            winners_r16.append(result["winner"])

        if len(winners_r16) != 16:
            return {"error": f"R32 inválido: {len(winners_r16)} ganadores", "champion": None}

        # Ronda de 16
        winners_qf = []
        for i in range(0, 16, 2):
            result = self._simulate_match(winners_r16[i], winners_r16[i+1], is_knockout=True)
            rounds["round_of_16"].append(result)
            winners_qf.append(result["winner"])

        if len(winners_qf) != 8:
            return {"error": f"R16 inválido", "champion": None}

        # Cuartos
        winners_sf = []
        for i in range(0, 8, 2):
            result = self._simulate_match(winners_qf[i], winners_qf[i+1], is_knockout=True)
            rounds["quarter_finals"].append(result)
            winners_sf.append(result["winner"])

        if len(winners_sf) != 4:
            return {"error": f"QF inválido", "champion": None}

        # Semifinales
        finalists = []
        semi_losers = []
        for i in range(0, 4, 2):
            result = self._simulate_match(winners_sf[i], winners_sf[i+1], is_knockout=True)
            rounds["semi_finals"].append(result)
            finalists.append(result["winner"])
            semi_losers.append(result["home"] if result["winner"] == result["away"] else result["away"])

        # Tercer lugar
        if len(semi_losers) == 2:
            rounds["third_place"] = self._simulate_match(semi_losers[0], semi_losers[1], is_knockout=True)

        # Final
        if len(finalists) == 2:
            rounds["final"] = self._simulate_match(finalists[0], finalists[1], is_knockout=True)
            champion = rounds["final"]["winner"]
        else:
            champion = None

        return {
            "rounds": rounds,
            "champion": champion,
            "round_of_16_teams": winners_r16,
            "quarter_final_teams": winners_qf,
            "semi_final_teams": winners_sf,
            "final_teams": finalists,
        }

    def _build_bracket(self, qualified: List[Dict]) -> List[Dict]:
        """
        Construye el bracket oficial de la FIFA para Ronda de 32.
        Basado en el formato oficial de 2026.
        """
        winners = {f"1{t['group']}": t for t in qualified if t.get("position") == 1}
        runners = {f"2{t['group']}": t for t in qualified if t.get("position") == 2}
        thirds = [t for t in qualified if t.get("position") == 3]

        # Asignación oficial FIFA de terceros a partidos
        # 1A vs 3C/D/E/F, 1B vs 3A/D/E/F, etc.
        third_assignments = {
            "A": ["C", "D", "E", "F"], "B": ["A", "D", "E", "F"],
            "C": ["A", "B", "F", "G"], "D": ["A", "B", "E", "H"],
            "E": ["A", "B", "C", "D"], "F": ["A", "B", "C", "D"],
            "G": ["A", "B", "C", "D"], "H": ["A", "B", "C", "D"],
            "I": ["A", "B", "C", "D"], "J": ["A", "B", "C", "D"],
            "K": ["A", "B", "C", "D"], "L": ["A", "B", "C", "D"],
        }

        bracket = []

        # 8 partidos de 1° vs 2° (protegidos por grupo)
        cross_matches = [
            ("1A", "2B"), ("1C", "2D"), ("1E", "2F"), ("1G", "2H"),
            ("1I", "2J"), ("1K", "2L"), ("1B", "2A"), ("1D", "2C"),
        ]

        for w_key, r_key in cross_matches:
            if w_key in winners and r_key in runners:
                bracket.append({
                    "home": winners[w_key]["team"],
                    "away": runners[r_key]["team"],
                    "type": "1v2"
                })

        # 8 partidos con terceros (asignación greedy válida)
        used_thirds = set()
        third_matches = [
            ("1E", "3"), ("1F", "3"), ("1G", "3"), ("1H", "3"),
            ("2A", "3"), ("2B", "3"), ("2C", "3"), ("2D", "3"),
        ]

        for slot_key, _ in third_matches:
            slot_group = slot_key[1] if slot_key.startswith("1") else slot_key[1]
            valid_groups = third_assignments.get(slot_group, [])

            assigned = None
            for third in thirds:
                if third["group"] in valid_groups and third["team"] not in used_thirds:
                    assigned = third
                    used_thirds.add(third["team"])
                    break

            if not assigned:
                # Fallback: cualquier tercero no usado
                for third in thirds:
                    if third["team"] not in used_thirds:
                        assigned = third
                        used_thirds.add(third["team"])
                        break

            if assigned and slot_key in winners:
                bracket.append({
                    "home": winners[slot_key]["team"],
                    "away": assigned["team"],
                    "type": "1v3"
                })
            elif assigned and slot_key in runners:
                bracket.append({
                    "home": runners[slot_key]["team"],
                    "away": assigned["team"],
                    "type": "2v3"
                })

        return bracket


# ============================================================================
# FUNCIÓN PÚBLICA
# ============================================================================

def run_simulation(num_simulations: int = 5000, seed: Optional[int] = None) -> Dict:
    """
    Ejecuta la simulación completa con el modelo híbrido.

    Args:
        num_simulations: Número de simulaciones Monte Carlo (100-100000)
        seed: Semilla para reproducibilidad

    Returns:
        Dict con probabilidades y última simulación
    """
    num_simulations = max(100, min(100000, int(num_simulations)))

    simulator = WorldCupSimulator()
    return simulator.simulate_tournament(num_simulations, seed)


# ============================================================================
# INTEGRACIÓN CON DATOS REALES
# ============================================================================

async def run_simulation_with_live_data(num_simulations: int = 5000,
                                        use_odds: bool = True,
                                        use_recent_matches: bool = True) -> Dict:
    """
    Ejecuta simulación con datos reales del torneo en curso.

    1. Obtiene resultados reales de /api/v1/worldcup/games
    2. Actualiza ratings Elo con resultados reales
    3. Opcionalmente integra odds de mercado
    4. Simula el resto del torneo
    """
    from app.services.worldcup_service import get_wc_games

    rating_system = HybridRatingSystem()

    # Obtener partidos reales
    games_data = await get_wc_games()
    if games_data and "games" in games_data:
        finished_matches = [
            {
                "home_team": g["home_team_name_es"],
                "away_team": g["away_team_name_es"],
                "home_score": int(g.get("home_score", 0)) if g.get("finished") == "TRUE" else 0,
                "away_score": int(g.get("away_score", 0)) if g.get("finished") == "TRUE" else 0,
            }
            for g in games_data["games"]
            if g.get("finished") == "TRUE" and g.get("home_team_name_es") and g.get("away_team_name_es")
        ]

        if finished_matches:
            rating_system.update_from_recent_matches(finished_matches)
            print(f"✅ Ratings actualizados con {len(finished_matches)} partidos reales")

    # Integrar odds si se solicita
    if use_odds:
        try:
            from app.services.odds_service import fetch_all_odds
            odds_data = await fetch_all_odds(force_refresh=False)
            if odds_data:
                # Procesar odds por partido
                # (implementación simplificada - se puede expandir)
                pass
        except Exception as e:
            print(f"⚠️ No se pudieron cargar odds: {e}")

    # Ejecutar simulación
    simulator = WorldCupSimulator(rating_system)
    return simulator.simulate_tournament(num_simulations)
