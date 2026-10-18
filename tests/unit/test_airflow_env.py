import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AIRFLOW_ENV = REPO / "docker" / "airflow" / "airflow.env"
ENV_EXAMPLE = REPO / ".env.example"
GENERATED_SECRETS = ("AIRFLOW_FERNET_KEY", "AIRFLOW_JWT_SECRET", "AIRFLOW_API_SECRET_KEY")


def env_example() -> dict[str, str]:
    pairs = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            pairs[key.strip()] = value.split("#", 1)[0].strip()
    return pairs


def test_every_variable_airflow_env_reads_is_in_env_example() -> None:
    # Compose substitutes an empty string for an unknown ${VAR}: a typo would start Airflow with
    # an empty secret instead of failing.
    settings = [line for line in AIRFLOW_ENV.read_text().splitlines() if not line.startswith("#")]
    used = set(re.findall(r"\$\{(\w+)", "\n".join(settings)))

    assert used - env_example().keys() == set()


def test_airflow_secrets_are_generated_by_make_secrets() -> None:
    example = env_example()

    assert {key: example.get(key) for key in GENERATED_SECRETS} == dict.fromkeys(
        GENERATED_SECRETS, "change_me"
    )
