"""Arguments of a DockerOperator that runs a job of the Spark image, as `make silver` does."""

import os
from typing import Any

from lakehouse.settings import Settings, spark_silver_environment


def spark_job_kwargs(pool: str, **extra: Any) -> dict[str, Any]:
    """For `DockerOperator(task_id=..., command=[job, *args], **kwargs)`, and for `.partial()`
    of a mapped task. The image's entrypoint takes the job name and its arguments. Same
    environment, network and limits as silver_upsert's merge; the secrets go to
    private_environment, which the Airflow UI does not render."""
    settings = Settings()
    public_env, private_env = spark_silver_environment(os.environ)
    return {
        "image": settings.spark_image,
        "network_mode": settings.lake_network,
        "environment": public_env,
        "private_environment": private_env,
        "mem_limit": "2g",
        # Airflow runs in a container: a host temp dir to mount does not exist.
        "mount_tmp_dir": False,
        "auto_remove": "success",
        "pool": pool,
        "do_xcom_push": False,
        **extra,
    }
