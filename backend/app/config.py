from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Real environment variables win; the root .env is a fallback when running on the host.
    # blank values in .env (SMTP_PORT=) mean "use the default"
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), extra="ignore", env_ignore_empty=True
    )

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
    # demo users (seed-demo-team), read from .env and never printed
    demo_user_password: SecretStr | None = None
    # the director (Ankur Sir): his user is made only when DIRECTOR_EMAIL is set in .env
    director_email: str | None = None
    director_name: str = "Ankur Shah"
    # email to our staff only: Mailpit catches everything until go-live (EMAIL_ENABLED=true)
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr | None = None
    smtp_from: str = "EESPL App <noreply@eespl.local>"
    mailpit_host: str = "mailpit"
    mailpit_port: int = 1025
    kylas_timeout_seconds: float = 20

    # Claude vision for survey photo suggestions (off unless enabled in survey settings). The key
    # comes from ANTHROPIC_API_KEY in .env only: never stored, logged or returned.
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_timeout_seconds: float = 60
    # the address phones reach the app on (set at go-live): delivery receipt links and QR codes
    public_base_url: str = "http://localhost:5174"


settings = Settings()
