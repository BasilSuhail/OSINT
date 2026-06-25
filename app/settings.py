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

    pushover_token: str = Field(default="")
    pushover_user: str = Field(default="")

    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")

    data_dir: str = Field(default="./data")

    retention_gdelt_days: int = Field(default=2)
    retention_news_days: int = Field(default=3)
    retention_hazard_days: int = Field(default=2)

    api_cors_origins: str = Field(default="http://localhost:3000")

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
