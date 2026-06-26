"""Central configuration, loaded from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_token: str = ""
    database_url: str = "sqlite:///./ghsearch.db"
    index_path: str = "./index_snapshot.pkl"


settings = Settings()
