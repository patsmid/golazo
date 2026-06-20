import duckdb
import json
import os
from app.config import DB_PATH, TEAMS, BASE_DIR

# Mapeo completo de nombres alternativos en el dataset histórico (inglés -> español de la app)
TEAM_NAME_MAPPING = {
    'Brazil': 'Brasil',
    'France': 'Francia',
    'Spain': 'España',
    'Germany': 'Alemania',
    'Italy': 'Italia',
    'Netherlands': 'Países Bajos',
    'Belgium': 'Bélgica',
    'Portugal': 'Portugal',
    'England': 'Inglaterra',
    'Croatia': 'Croacia',
    'Morocco': 'Marruecos',
    'Senegal': 'Senegal',
    'Ghana': 'Ghana',
    'Cameroon': 'Camerún',
    'Nigeria': 'Nigeria',
    'Tunisia': 'Túnez',
    'Algeria': 'Argelia',
    'Egypt': 'Egipto',
    'United States': 'Estados Unidos',
    'Mexico': 'México',
    'Canada': 'Canadá',
    'Costa Rica': 'Costa Rica',
    'Japan': 'Japón',
    'South Korea': 'Corea del Sur',
    'Australia': 'Australia',
    'Saudi Arabia': 'Arabia Saudita',
    'Uruguay': 'Uruguay',
    'Colombia': 'Colombia',
    'Ecuador': 'Ecuador',
    'Peru': 'Perú',
    'Chile': 'Chile',
    'Paraguay': 'Paraguay',
    'Argentina': 'Argentina',
    'Denmark': 'Dinamarca',
    'Serbia': 'Serbia',
    'Switzerland': 'Suiza',
    'Poland': 'Polonia',
    'Turkey': 'Turquía',
    'Czech Republic': 'República Checa',
    'South Africa': 'Sudáfrica',
    'Bosnia and Herzegovina': 'Bosnia y Herzegovina',
    'Qatar': 'Catar',
    'Haiti': 'Haití',
    'Scotland': 'Escocia',
    'Curaçao': 'Curazao',
    'Ivory Coast': 'Costa de Marfil',
    'Sweden': 'Suecia',
    'Iran': 'Irán',
    'New Zealand': 'Nueva Zelanda',
    'Cape Verde': 'Cabo Verde',
    'Iraq': 'Irak',
    'Norway': 'Noruega',
    'Austria': 'Austria',
    'Jordan': 'Jordania',
    'Uzbekistan': 'Uzbekistán',
    'Democratic Republic of the Congo': 'Rep. Dem. del Congo',
    'Panama': 'Panamá',
}


def create_connection():
    return duckdb.connect(DB_PATH)


def load_historical_data(csv_path: str):
    """Carga el CSV histórico en DuckDB manejando valores NA correctamente."""
    conn = create_connection()

    # Eliminar tabla si existe
    conn.execute("DROP TABLE IF EXISTS matches")

    print(f"Cargando CSV desde {csv_path}...")
    conn.execute(f"""
        CREATE TABLE matches AS
        SELECT * FROM read_csv_auto('{csv_path.replace(chr(92), '/')}',
            types={{
                'home_score': 'VARCHAR',
                'away_score': 'VARCHAR'
            }}
        )
    """)

    # Reemplazar 'NA' por NULL y convertir a DOUBLE
    conn.execute("UPDATE matches SET home_score = NULL WHERE home_score = 'NA'")
    conn.execute("UPDATE matches SET away_score = NULL WHERE away_score = 'NA'")

    conn.execute("""
        ALTER TABLE matches
        ALTER COLUMN home_score TYPE DOUBLE USING COALESCE(TRY_CAST(home_score AS DOUBLE), NULL)
    """)
    conn.execute("""
        ALTER TABLE matches
        ALTER COLUMN away_score TYPE DOUBLE USING COALESCE(TRY_CAST(away_score AS DOUBLE), NULL)
    """)

    columns = conn.execute("DESCRIBE matches").fetchall()
    print(f"Columnas detectadas: {[col[0] for col in columns]}")

    count = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    print(f"✅ Tabla 'matches' creada con {count:,} filas")

    sample = conn.execute("""
        SELECT date, home_team, away_team, home_score, away_score
        FROM matches
        WHERE home_score IS NOT NULL
        LIMIT 3
    """).fetchall()
    print("Muestra de partidos:")
    for row in sample:
        print(f"  {row[0]} | {row[1]} vs {row[2]}: {row[3]}-{row[4]}")

    future = conn.execute("SELECT COUNT(*) FROM matches WHERE home_score IS NULL").fetchone()[0]
    print(f"Partidos sin goles (futuros/desconocidos): {future}")

    conn.close()


def load_fifa_ranking() -> dict:
    """Carga puntos FIFA desde data/fifa_ranking.json y los convierte a Elo."""
    fifa_path = os.path.join(BASE_DIR, "data", "fifa_ranking.json")
    if not os.path.exists(fifa_path):
        return {}
    with open(fifa_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Esperamos un dict {team_name: points}
    elo_ratings = {}
    for team, points in data.items():
        if team in TEAMS:
            # Conversión simple: Elo = 1500 + (points - 1000) * 0.5
            elo = 1500 + (points - 1000) * 0.5
            elo_ratings[team] = max(1200, min(2000, elo))
    return elo_ratings

def compute_initial_elo():
    """Calcula o carga Elo inicial. Prioriza elo_initial.json, luego fifa_ranking.json, luego 1500."""
    elo_path = os.path.join(BASE_DIR, "data", "elo_initial.json")
    if os.path.exists(elo_path):
        with open(elo_path, "r", encoding="utf-8") as f:
            elo_ratings = json.load(f)
        print(f"✅ Elo inicial cargado desde {elo_path}")
        return elo_ratings

    fifa_elo = load_fifa_ranking()
    if fifa_elo:
        # Guardar como elo_initial.json para futuras ejecuciones
        with open(elo_path, "w", encoding="utf-8") as f:
            json.dump(fifa_elo, f, indent=2, ensure_ascii=False)
        print(f"✅ Elo inicial generado desde FIFA ranking ({len(fifa_elo)} equipos)")
        return fifa_elo

    # Fallback: 1500
    print("⚠️ No se encontró fuente de Elo. Usando 1500 para todos.")
    elo_ratings = {team: 1500.0 for team in TEAMS}
    with open(elo_path, "w", encoding="utf-8") as f:
        json.dump(elo_ratings, f, indent=2, ensure_ascii=False)
    return elo_ratings


if __name__ == "__main__":
    csv_file = os.path.join(BASE_DIR, "data", "historical_results.csv")

    if not os.path.exists(csv_file):
        print(f"❌ Error: No se encuentra {csv_file}")
        print("Descarga: https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2023")
        exit(1)

    load_historical_data(csv_file)
    compute_initial_elo()
