"""
Application configuration for birdseye.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/birdseye"
    )
    storage_root: str = Field(default="data/birdseye")

    asset_base_url: str = Field(
        default="http://localhost:8001/data",
        description="Base URL for serving large asset files (orthophotos, point clouds, etc.)",
    )

    class Config:
        env_file = ".env"
        env_prefix = "BIRDSEYE_"


settings = Settings()
