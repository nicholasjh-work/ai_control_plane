# Standalone migration script — run with: python -m app.db.migrate — Nicholas Hidalgo
from sqlalchemy import text

from app.db.connection import engine
from app.db.models import Base

if __name__ == "__main__":
    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        conn.execute(
            text(
                "ALTER TABLE ai_control_plane_audit "
                "ADD COLUMN IF NOT EXISTS summary TEXT"
            )
        )
        conn.commit()

    print("Tables created: ai_control_plane_audit, ai_control_plane_runs")
