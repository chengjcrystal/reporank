"""Central configuration, loaded from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_token: str = ""
    database_url: str = "sqlite:///./ghsearch.db"
    index_path: str = "./index_snapshot.pkl"
    cache_size: int = 1024  # LRU search-result cache entries; 0 disables


settings = Settings()
