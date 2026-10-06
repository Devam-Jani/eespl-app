from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Real environment variables win; the root .env is a fallback when running on the host.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str
    cors_origins: list[str] = ["http://localhost:5174"]

    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    # Set to true when served over HTTPS so the refresh cookie is never sent in clear text.
    cookie_secure: bool = False


settings = Settings()
