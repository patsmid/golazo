from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.services.simulation_service import run_simulation, run_simulation_with_live_data

router = APIRouter(prefix="/api/v1")

@router.get("/simulation/run")
async def run_simulation_endpoint(
    num_simulations: int = Query(5000, ge=100, le=100000, description="Número de simulaciones Monte Carlo"),
    seed: Optional[int] = Query(None, description="Semilla para reproducibilidad"),
    use_live_data: bool = Query(True, description="Usar datos reales del torneo en curso"),
    use_odds: bool = Query(True, description="Integrar odds de mercado")
):
    """
    Ejecuta simulación Monte Carlo del Mundial 2026 con modelo híbrido.

    ## Modelo
    - **Elo ratings**: Basados en eloratings.net (Junio 2026)
    - **Dixon-Coles**: Corrección de bajo score (ρ = -0.13)
    - **Forma reciente**: Actualización con resultados reales del torneo
    - **Odds de mercado**: Ajuste bayesiano suave
    - **Localía real**: Hosts (USA, México, Canadá) con ventaja en sus estadios
    - **Fatiga**: Penalización acumulativa por partidos jugados

    ## Parámetros
    - `num_simulations`: 100 a 100,000 (default: 5,000)
    - `seed`: Semilla para reproducibilidad
    - `use_live_data`: Actualiza ratings con resultados reales del torneo
    - `use_odds`: Integra odds de casas de apuestas (sin gastar créditos, usa caché)

    ## Respuesta
    ```json
    {
        "num_simulations": 5000,
        "probabilities": {
            "champion": {"Spain": 0.166, "Argentina": 0.119, ...},
            "finalist": {"Spain": 0.259, "Argentina": 0.246, ...},
            "semi_finalist": {...},
            "quarter_finalist": {...},
            "round_of_16": {...},
            "round_of_32": {...},
            "qualified": {...},
            "group_winners": {"A": {"Mexico": 0.45, ...}, ...},
            "group_runners_up": {...},
            "group_third": {...}
        },
        "last_simulation": {
            "group_stage": {...},
            "knockout": {...}
        },
        "ratings_snapshot": {
            "Mexico": {"base_elo": 1818, "current_elo": 1835.2, "effective_elo": 1840.2, ...}
        }
    }
    ```
    """
    try:
        if use_live_data:
            result = await run_simulation_with_live_data(
                num_simulations=num_simulations,
                use_odds=use_odds
            )
        else:
            result = run_simulation(num_simulations=num_simulations, seed=seed)

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en simulación: {str(e)}")


@router.get("/simulation/ratings")
async def get_current_ratings():
    """
    Obtiene los ratings Elo actuales de todos los equipos.
    """
    try:
        from app.services.simulation_service import HybridRatingSystem, HOSTS, HOST_ELO_BOOST

        rating_system = HybridRatingSystem()

        return {
            "ratings": {
                team: {
                    "name": r.name,
                    "base_elo": r.base_elo,
                    "current_elo": round(r.current_elo, 1),
                    "effective_elo": round(r.effective_elo, 1),
                    "form_adjustment": round(r.form_adjustment, 1),
                    "odds_adjustment": round(r.odds_adjustment, 1),
                    "fatigue": round(r.fatigue, 1),
                    "attack_strength": round(r.attack_strength, 3),
                    "defense_strength": round(r.defense_strength, 3),
                }
                for team, r in rating_system.ratings.items()
            },
            "hosts": list(HOSTS),
            "host_advantage": HOST_ELO_BOOST
        }
    except Exception as e:
        import traceback
        print(f"RATINGS ERROR: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error en ratings: {str(e)}")
