"""Configuration for the OLTP side: everything comes from the environment or `.env`."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Source database connection.

    Inside compose the DSN arrives ready-made as OLTP_DSN. Run from the repo root there is no
    such variable, so it is assembled from the same pieces `make secrets` wrote into `.env`.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    oltp_dsn: str | None = None
    oltp_user: str = "shop"
    oltp_password: str = ""
    oltp_db: str = "shop"
    oltp_host: str = Field(default="127.0.0.1", validation_alias="BIND_IP")
    oltp_port: int = 5432

    @property
    def dsn(self) -> str:
        if self.oltp_dsn:
            return self.oltp_dsn
        return (
            f"postgresql://{self.oltp_user}:{self.oltp_password}"
            f"@{self.oltp_host}:{self.oltp_port}/{self.oltp_db}"
        )
