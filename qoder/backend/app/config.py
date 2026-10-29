from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    seekdb_path: str = "./data/experiments.db"
    seekdb_collection: str = "experiments"
    powercontext_url: str = "http://127.0.0.1:8000"
    powercontext_scope: str = "lab-notebook"
    host: str = "0.0.0.0"
    port: int = 8080

    model_config = {"env_file": ".env"}


settings = Settings()
