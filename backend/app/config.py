from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REPLICATE_API_TOKEN: str
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000", "https://statesofbeing.art"]
    MAX_UPLOAD_MB: int = 100

    class Config:
        env_file = ".env"


settings = Settings()
