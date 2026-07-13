"""Runtime settings, loaded from environment via pydantic-settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="osint")
    postgres_user: str = Field(default="osint")
    postgres_password: str = Field(default="")

    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)

    fred_api_key: str = Field(default="")
    firms_map_key: str = Field(default="")
    acled_username: str = Field(default="")
    acled_password: str = Field(default="")
    acled_api_enabled: bool = Field(default=False)
    acled_csv_path: str = Field(default="")
    acled_csv_dir: str = Field(default="")
    emdat_csv_path: str = Field(default="")
    cyber_geo_enabled: bool = Field(default=True)
    cyber_geo_max_lookups: int = Field(default=25)

    pushover_token: str = Field(default="")
    pushover_user: str = Field(default="")

    # WS-G local LLM validator (#378) — localhost only, never a cloud API.
    ollama_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="qwen3.5:4b-q4_K_M")
    validator_batch_limit: int = Field(default=200)

    # The brain (#409) — a light always-warm-when-idle local model, separate
    # from the 4b nightly validator above. Localhost only.
    brain_enabled: bool = Field(default=True)
    brain_model: str = Field(default="qwen2.5:1.5b-instruct-q4_K_M")
    # Refuse to load the model unless at least this much RAM is free (Pi guard).
    brain_min_free_mb: int = Field(default=1200)
    brain_keep_alive: str = Field(default="30m")

    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")

    data_dir: str = Field(default="./data")

    retention_gdelt_days: int = Field(default=30)
    retention_news_days: int = Field(default=30)
    retention_hazard_days: int = Field(default=30)
    # Hard ceiling on DB disk use; oldest event-days are trimmed when exceeded.
    storage_cap_gb: int = Field(default=30)
    # Size-cap enforcement never deletes events newer than this many days.
    storage_cap_floor_days: int = Field(default=7)

    api_cors_origins: str = Field(default="http://localhost:3000,http://localhost:3001")

    @property
    def postgres_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


settings = Settings()
