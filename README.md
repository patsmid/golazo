# ⚽ Golazo - Predicciones del Mundial 2026

Sistema de predicción de partidos del Mundial 2026 basado en **Elo histórico**, **modelo Dixon-Coles** y **sentimiento de noticias**, enriquecido con **odds de casas de apuestas** en tiempo real. Incluye una API REST y un frontend moderno.

## 🚀 Demo en vivo

- **API**: [https://golazo-api.onrender.com/api/v1/predictions/today](https://golazo-api.onrender.com/api/v1/predictions/today)
- **Frontend**: [https://golazowc.netlify.app](https://golazowc.netlify.app)

## 📦 Stack tecnológico

### Backend
- FastAPI (Python)
- Elo + Dixon-Coles (estadística)
- Groq (análisis de sentimiento y texto)
- The Odds API (odds de casas)
- Redis (caché)
- Render (deploy)

### Frontend
- React 18 + Vite
- Tailwind CSS v4
- Axios (consumo de API)
- Lucide React (íconos)
- Vercel / Netlify (deploy)

## 🛠️ Instalación local

### Requisitos
- Python 3.12+
- Node.js 18+
- npm

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

Frontend
bash

cd frontend
npm install
npm run dev

Abre http://localhost:5173
🔑 Variables de entorno

Crea un archivo .env en cada carpeta:
Backend (.env)
text

GROQ_API_KEY=tu_clave
ODDS_API_KEY=tu_clave
REDIS_URL=redis://localhost:6379  # opcional

Frontend (.env.local)
text

VITE_API_URL=http://localhost:8000/api/v1

📊 Endpoints principales
Método	Ruta	Descripción
GET	/api/v1/predictions/today	Predicciones para hoy
GET	/api/v1/predictions/{match_id}	Predicción de un partido
POST	/api/v1/predictions/refresh	Regenera caché
POST	/api/v1/predictions/learn	Aprende de partidos jugados
POST	/api/v1/predictions/recalculate	Reinicia Elo
🧠 Modelo de predicción

    Elo inicial: basado en ranking FIFA (convertido a Elo).

    Actualización en vivo: tras cada partido real.

    Goles esperados (xG): a partir de la diferencia de Elo.

    Dixon-Coles: matriz de probabilidades de marcador.

    Sentimiento: análisis de noticias con Groq.

    Odds: consenso de casas de apuestas.

    Análisis experto: generado por Groq.

🚀 Despliegue
Backend en Render

    Conecta el repositorio a Render.

    Configura:

        Build Command: pip install -r requirements.txt

        Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT

        Variables de entorno: GROQ_API_KEY, ODDS_API_KEY.

Frontend en Netlify / Vercel

    Conecta el repositorio.

    Indica la Base directory: frontend.

    Comando de build: npm run build.

    Publicar directorio: frontend/dist.

    Añade la variable VITE_API_URL apuntando a la API desplegada.

🤝 Contribuciones

Las contribuciones son bienvenidas. Abre un issue o un pull request.
📄 Licencia

MIT
