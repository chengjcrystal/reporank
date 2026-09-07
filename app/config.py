"""Central configuration, loaded from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_token: str = ""
    anthropic_api_key: str = ""  # optional; enables LLM query expansion (app/search/query_expand.py)
    database_url: str = "sqlite:///./ghsearch.db"
    index_path: str = "./index_snapshot.pkl"
    eval_index_path: str = "./eval_index.pkl"  # frozen snapshot the CI gate scores against
    cache_size: int = 1024  # LRU search-result cache entries; 0 disables


settings = Settings()
