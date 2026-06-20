import os
from dotenv import load_dotenv

load_dotenv()

# Directorio base
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# DuckDB
DB_PATH = os.path.join(BASE_DIR, "data", "worldcup.db")

# APIs
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

# Redis (Upstash)
REDIS_URL = os.getenv("UPSTASH_REDIS_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_TOKEN")
APIFOOTBALL_KEY = os.getenv("APIFOOTBALL_KEY")

# Mundial
WORLD_CUP_YEAR = 2026

# 48 equipos del Mundial 2026 (nombres en español, consistentes con toda la app)
TEAMS = [
    # Grupo A
    "México", "Sudáfrica", "Corea del Sur", "República Checa",
    # Grupo B
    "Canadá", "Bosnia y Herzegovina", "Catar", "Suiza",
    # Grupo C
    "Brasil", "Marruecos", "Haití", "Escocia",
    # Grupo D
    "Estados Unidos", "Paraguay", "Australia", "Turquía",
    # Grupo E
    "Alemania", "Curazao", "Costa de Marfil", "Ecuador",
    # Grupo F
    "Países Bajos", "Japón", "Suecia", "Túnez",
    # Grupo G
    "Bélgica", "Egipto", "Irán", "Nueva Zelanda",
    # Grupo H
    "España", "Cabo Verde", "Arabia Saudita", "Uruguay",
    # Grupo I
    "Francia", "Senegal", "Irak", "Noruega",
    # Grupo J
    "Argentina", "Argelia", "Austria", "Jordania",
    # Grupo K
    "Portugal", "Rep. Dem. del Congo", "Uzbekistán", "Colombia",
    # Grupo L
    "Inglaterra", "Croacia", "Ghana", "Panamá",
]
