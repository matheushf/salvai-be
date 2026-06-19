from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    supabase_url: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

    cors_allowed_origins: str = ""

    # Optional API key for the public Instagram scraper endpoint.
    # When set, requests without a matching X-Api-Key header are rejected.
    # Leave empty (default) to keep the endpoint open (useful in dev).
    instagram_api_key: str = ""

    # Optional Instagram credentials for the scraper. When set, the scraper
    # loads a saved session file instead of hitting the GraphQL API anonymously,
    # which raises the rate-limit ceiling significantly.
    # Create the session file with: instaloader -l USERNAME
    instagram_username: str = ""
    instagram_session_file: str = ""

    # Optional salvai-scraper service for generic web page enrichment.
    scraper_service_url: str = ""
    scraper_api_key: str = ""

    # SQLite cache for GET /api/v1/enrich (shared across uvicorn workers via WAL).
    enrich_cache_enabled: bool = True
    enrich_cache_db_path: str = "./data/enrich_cache.db"

    # Optional Sentry error monitoring. Leave SENTRY_DSN empty to disable (default for local dev).
    sentry_dsn: str = ""
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 0.0
    sentry_release: str = ""

    # Universal / app links for https://salvai.cloud/events/{id}
    share_base_url: str = "https://salvai.cloud"
    ios_app_team_id: str = "FTHN8739FL"
    ios_bundle_id: str = "com.matheushf.salvai"
    android_package_name: str = "com.matheushf.salvai"
    # Comma-separated SHA-256 cert fingerprints for Android App Links verification.
    android_sha256_cert_fingerprints: str = ""
    ios_app_store_url: str = "https://apps.apple.com/app/salvai/id0000000000"
    android_play_store_url: str = (
        "https://play.google.com/store/apps/details?id=com.matheushf.salvai"
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def supabase_jwt_issuer(self) -> str:
        """Expected 'iss' claim in Supabase JWTs: <project-url>/auth/v1"""
        return f"{self.supabase_url.rstrip('/')}/auth/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
