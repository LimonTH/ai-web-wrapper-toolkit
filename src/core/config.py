from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    project_root: str = str(Path(__file__).parent.parent.parent)

    cors_origins: str = "*"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"

    model_config = {"env_prefix": "AWT_", "env_file": ".env"}

    @property
    def database_url(self) -> str:
        data_path = Path(self.project_root) / "data" / "toolkit.db"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{data_path}"


settings = Settings()
