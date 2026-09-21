"""Configuration for the OLTP side: everything comes from the environment or `.env`."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Source database connection and replay knobs.

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

    # Virtual seconds per real second. 2880 replays one day of history every 30 seconds.
    replay_speed: float = 2880.0
    # Share of the history bulk-loaded before the clock starts; the rest is replayed.
    replay_initial_share: float = 0.8
    # Share of delivery updates held back by replay_late_delay_seconds of real time.
    replay_late_ratio: float = 0.0
    replay_late_delay_seconds: int = 300
    # Share of updates emitted twice, byte for byte, to exercise dedup downstream.
    replay_duplicate_ratio: float = 0.0
    replay_schema_evolution_at: str = ""

    http_port: int = 8000
    # How many due events one pass of the loop claims. Bounds memory and transaction size.
    replay_batch_size: int = 500

    @property
    def dsn(self) -> str:
        if self.oltp_dsn:
            return self.oltp_dsn
        return (
            f"postgresql://{self.oltp_user}:{self.oltp_password}"
            f"@{self.oltp_host}:{self.oltp_port}/{self.oltp_db}"
        )
