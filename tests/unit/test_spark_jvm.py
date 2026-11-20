import pytest
from spark_jvm import SKIP_REASON, java_binary, java_major


@pytest.mark.parametrize(
    ("text", "major"),
    [
        ('openjdk version "25.0.5" 2026-04-21\nOpenJDK Runtime Environment', 25),
        ('openjdk version "17.0.21" 2026-04-21', 17),
        ('java version "1.8.0_392"', 8),
        ('openjdk version "11"', 11),
        ("", None),
        ("command not found: java", None),
        ('version "x.y"', None),
    ],
)
def test_java_major_reads_the_version_line(text: str, major: int | None) -> None:
    assert java_major(text) == major


def test_skip_reason_names_java_17() -> None:
    assert "Java 17" in SKIP_REASON


def test_java_binary_prefers_java_home_like_spark_class() -> None:
    assert java_binary({"JAVA_HOME": "/opt/jdk17"}) == "/opt/jdk17/bin/java"


@pytest.mark.parametrize("environ", [{}, {"JAVA_HOME": ""}])
def test_java_binary_falls_back_to_path(environ: dict[str, str]) -> None:
    assert java_binary(environ) == "java"
