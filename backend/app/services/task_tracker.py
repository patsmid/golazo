import json
import time
from typing import Optional, Dict, Any
from app.cache.redis_client import redis_client

TASK_PREFIX = "task:"

def start_task(task_id: str, task_type: str, details: Dict[str, Any] = None):
    """Registra el inicio de una tarea."""
    task_data = {
        "task_type": task_type,
        "status": "running",
        "started_at": time.time(),
        "details": details or {},
        "progress": 0,
        "message": "Iniciando..."
    }
    redis_client.setex(f"{TASK_PREFIX}{task_id}", 3600, json.dumps(task_data))  # expira en 1 hora

def update_task_progress(task_id: str, progress: int, message: str):
    """Actualiza el progreso de una tarea."""
    data = get_task_status(task_id)
    if data:
        data["progress"] = progress
        data["message"] = message
        redis_client.setex(f"{TASK_PREFIX}{task_id}", 3600, json.dumps(data))

def complete_task(task_id: str, result: Dict[str, Any] = None):
    """Marca una tarea como completada."""
    data = get_task_status(task_id)
    if data:
        data["status"] = "completed"
        data["completed_at"] = time.time()
        data["result"] = result or {}
        data["message"] = "Completada exitosamente"
        redis_client.setex(f"{TASK_PREFIX}{task_id}", 3600, json.dumps(data))

def fail_task(task_id: str, error: str):
    """Marca una tarea como fallida."""
    data = get_task_status(task_id)
    if data:
        data["status"] = "failed"
        data["error"] = error
        data["message"] = f"Error: {error[:100]}"
        redis_client.setex(f"{TASK_PREFIX}{task_id}", 3600, json.dumps(data))

def get_task_status(task_id: str) -> Optional[Dict]:
    """Obtiene el estado de una tarea."""
    raw = redis_client.get(f"{TASK_PREFIX}{task_id}")
    if raw:
        return json.loads(raw)
    return None

def generate_task_id() -> str:
    """Genera un ID único para una tarea."""
    return f"task_{int(time.time())}_{id(object())}"
