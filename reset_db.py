# Guarda esto como reset_db.py en la raíz del proyecto
import duckdb
import os

db_path = os.path.join("data", "worldcup.db")
conn = duckdb.connect(db_path)

# Borrar tabla existente
conn.execute("DROP TABLE IF EXISTS matches")
print("✅ Tabla eliminada")

conn.close()
