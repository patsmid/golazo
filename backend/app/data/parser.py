import feedparser
from typing import List
from urllib.parse import quote


def fetch_news_headlines(team_name: str, lang="es") -> List[str]:
    """Obtiene titulares de Google News RSS para un equipo."""
    query = quote(f"{team_name} mundial 2026")
    url = f"https://news.google.com/rss/search?q={query}&hl={lang}&gl=MX&ceid=MX:{lang}"
    try:
        feed = feedparser.parse(url)
        headlines = [entry.title for entry in feed.entries[:5]]
        return headlines if headlines else [f"No se encontraron noticias sobre {team_name}"]
    except Exception as e:
        print(f"Error fetching news: {e}")
        return [f"Error al obtener noticias de {team_name}"]
