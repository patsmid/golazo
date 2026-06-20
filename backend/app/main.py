from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import predictions, admin  # si tienes admin

app = FastAPI(title="Golazo API - Mundial 2026")

# Configurar CORS para permitir peticiones desde el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",          # desarrollo Vite
        "https://tu-frontend.vercel.app", # producción (cambiar después)
        "https://tu-frontend.netlify.app",
        # También puedes usar ["*"] solo para pruebas
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(predictions.router)
# app.include_router(admin.router)  # si existe

@app.get("/")
async def root():
    return {"message": "Golazo API - Mundial 2026", "status": "online"}
