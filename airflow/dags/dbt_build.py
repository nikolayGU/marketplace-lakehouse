"""dbt_build: dbt build of lake.gold after every silver merge (Asset lake.silver, D10).

No retries: a failed test stays failed. A manual run takes dbt vars from its conf, as
{"dbt_vars": "{chaos_break_test: true}"} (chaos 9); a run from the Asset has an empty conf.
"""

from datetime import datetime

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Asset, dag
from lakehouse.settings import SILVER_ASSET_NAME, dbt_command


@dag(
    schedule=[Asset(SILVER_ASSET_NAME)],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    tags=["gold"],
)
def dbt_build() -> None:
    BashOperator(
        task_id="dbt_build",
        bash_command=dbt_command("build") + ' --vars "$DBT_VARS"',
        # Through the environment, not the command line: the vars never pass the shell parser.
        env={"DBT_VARS": "{{ (dag_run.conf or {}).get('dbt_vars', '{}') }}"},
        append_env=True,
    )


dbt_build()
