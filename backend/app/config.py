from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REPLICATE_API_TOKEN: str
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000", "https://statesofbeing.art"]
    MAX_UPLOAD_MB: int = 100
    LIBRARY_DIR: str = "/data/library"

    # Global daily spend cap (Replicate cost control).
    # Cap is in USD per UTC day; each processed song is charged the estimated
    # Replicate cost below (Demucs ~$0.035 + allin1 ~$0.10). Default $5/day.
    DAILY_SPEND_CAP_USD: float = 5.0
    COST_PER_REQUEST_USD: float = 0.135

    # Number of trusted proxies in front of the app (Railway edge = 1). Used to
    # pick the real client IP from X-Forwarded-For for per-IP rate limiting.
    TRUSTED_PROXY_HOPS: int = 1

    class Config:
        env_file = ".env"


settings = Settings()
