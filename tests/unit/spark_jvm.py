"""Whether this host can start a local SparkSession (Spark 3.5 needs Java 17 or 11)."""

import os
import re
import subprocess
from collections.abc import Mapping
from functools import lru_cache

SKIP_REASON = "local SparkSession needs Java 17 (Spark 3.5); CI and the image have it"
SUPPORTED_MAJORS = (17, 11)

VERSION = re.compile(r'version "(\d+)(?:\.(\d+))?')


def java_major(text: str) -> int | None:
    """Major Java version from the output of `java -version`, None if it is not recognised."""
    match = VERSION.search(text)
    if not match:
        return None
    major = int(match.group(1))
    if major == 1 and match.group(2):
        return int(match.group(2))
    return major


def java_binary(environ: Mapping[str, str]) -> str:
    """The java that pyspark's spark-class runs: $JAVA_HOME/bin/java when set, else PATH."""
    home = environ.get("JAVA_HOME")
    return os.path.join(home, "bin", "java") if home else "java"


@lru_cache(maxsize=1)
def has_spark_jvm() -> bool:
    try:
        result = subprocess.run(
            [java_binary(os.environ), "-version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return java_major(result.stderr or result.stdout) in SUPPORTED_MAJORS


HAS_SPARK_JVM = has_spark_jvm()
