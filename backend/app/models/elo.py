import json
import os
from app.config import BASE_DIR, TEAMS

class EloManager:
    def __init__(self):
        self.ratings = {}
        self.file_path = os.path.join(BASE_DIR, "data", "elo_ratings.json")
        self.load()

    def load(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as f:
                self.ratings = json.load(f)
            print(f"✅ Elo cargado: {len(self.ratings)} equipos desde {self.file_path}")
        else:
            # Intentar cargar desde FIFA ranking
            fifa_path = os.path.join(BASE_DIR, "data", "fifa_ranking.json")
            if os.path.exists(fifa_path):
                with open(fifa_path, "r", encoding="utf-8") as f:
                    fifa_data = json.load(f)
                self.ratings = {}
                for team, points in fifa_data.items():
                    if team in TEAMS:
                        # Conversión simple: 1500 + (points - 1000) * 0.5
                        elo = 1500 + (points - 1000) * 0.5
                        self.ratings[team] = max(1200, min(2000, elo))
                # Completar equipos faltantes con 1500
                for team in TEAMS:
                    if team not in self.ratings:
                        self.ratings[team] = 1500.0
                self.save()
                print(f"✅ Elo generado desde FIFA ranking ({len(self.ratings)} equipos)")
            else:
                self.ratings = {team: 1500.0 for team in TEAMS}
                self.save()
                print("⚠️ Usando ratings Elo por defecto (1500)")

    def save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, "w") as f:
            json.dump(self.ratings, f, indent=2)

    def get_rating(self, team: str) -> float:
        return self.ratings.get(team, 1500.0)

    def reset_to_initial(self):
        self.ratings = {team: 1500.0 for team in TEAMS}
        self.save()
        print("✅ Elo reseteado a 1500.")

    def update_match(self, home_team: str, away_team: str, home_goals: int, away_goals: int, K: int = 30, is_host_match: bool = False) -> dict:
        home_adv = 100 if is_host_match else 0
        rating_home = self.ratings.get(home_team, 1500)
        rating_away = self.ratings.get(away_team, 1500)
        dr = rating_home - rating_away + home_adv
        we_home = 1.0 / (10**(-dr/400) + 1)
        if home_goals > away_goals:
            w_home = 1.0
        elif home_goals == away_goals:
            w_home = 0.5
        else:
            w_home = 0.0
        old_home = rating_home
        old_away = rating_away
        new_home = rating_home + K * (w_home - we_home)
        new_away = rating_away + K * ((1 - w_home) - (1 - we_home))
        self.ratings[home_team] = new_home
        self.ratings[away_team] = new_away
        self.save()
        return {
            "home": {"team": home_team, "old": round(old_home, 1), "new": round(new_home, 1), "delta": round(new_home - old_home, 1)},
            "away": {"team": away_team, "old": round(old_away, 1), "new": round(new_away, 1), "delta": round(new_away - old_away, 1)},
            "expected_home_win_prob": round(we_home, 4),
            "result": "home" if home_goals > away_goals else "draw" if home_goals == away_goals else "away",
            "score": f"{home_goals}-{away_goals}"
        }
