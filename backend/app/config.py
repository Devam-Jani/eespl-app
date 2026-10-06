from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Real environment variables win; the root .env is a fallback when running on the host.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str
    cors_origins: list[str] = ["http://localhost:5174"]


settings = Settings()
