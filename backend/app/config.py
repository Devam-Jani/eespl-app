from pydantic import Field, SecretStr
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
    # Uploaded files (company logo, later documents). A Docker volume, never in git.
    media_dir: str = "/media"

    # Kylas CRM. Off unless KYLAS_ENABLED=true AND a key AND a source id (company settings) are
    # set. The key is only ever sent as the api-key header: never logged, stored or shown.
    kylas_enabled: bool = False
    kylas_base_url: str = "https://api.kylas.io/v1"
    kylas_api_key: SecretStr | None = None
    kylas_timeout_seconds: float = 20

    # Claude vision for survey photo suggestions (off unless enabled in survey settings). The key
    # comes from ANTHROPIC_API_KEY in .env only: never stored, logged or returned.
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_timeout_seconds: float = 60
    # the address phones reach the app on (set at go-live): delivery receipt links and QR codes
    public_base_url: str = "http://localhost:5174"


settings = Settings()
