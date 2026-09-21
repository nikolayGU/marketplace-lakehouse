"""Download the Olist dataset into `data/raw`.

The dataset is public, so the Kaggle CLI serves it without credentials. Set up auth only if
Kaggle starts asking for it (`kaggle auth login`, or KAGGLE_API_TOKEN in the environment).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

SLUG = "olistbr/brazilian-ecommerce"
FILES = (
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
)

AUTH_HELP = """
Kaggle refused the download. The dataset is public, so this usually means Kaggle now wants an
account. Pick one:
  uv run kaggle auth login                      # browser flow
  export KAGGLE_API_TOKEN=<token from kaggle.com/settings/api>
  ~/.kaggle/access_token                        # same token, in a file
Then run `make data` again.
"""


def raw_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "./data")) / "raw"


def missing(target: Path) -> list[str]:
    return [f for f in FILES if not (target / f).is_file() or (target / f).stat().st_size == 0]


def download(target: Path) -> None:
    kaggle = shutil.which("kaggle")
    if kaggle is None:
        raise SystemExit("kaggle CLI not found; run `uv sync --group dev` first")
    target.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [kaggle, "datasets", "download", SLUG, "-p", str(target), "--unzip", "--force"],
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(AUTH_HELP)


def main() -> int:
    target = raw_dir()
    if not missing(target):
        print(f"{target}: all {len(FILES)} files present, nothing to do")
        return 0
    download(target)
    still_missing = missing(target)
    if still_missing:
        print(
            f"download finished but these are missing: {', '.join(still_missing)}", file=sys.stderr
        )
        return 1
    total = sum((target / f).stat().st_size for f in FILES)
    print(f"{target}: {len(FILES)} files, {total / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
