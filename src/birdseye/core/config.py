"""
Application configuration for birdseye.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):  # type: ignore[misc]
    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/birdseye"
    )
    storage_root: str = Field(default="/data/birdseye")

    class Config:
        env_file = ".env"
        env_prefix = "BIRDSEYE_"


settings = Settings()
