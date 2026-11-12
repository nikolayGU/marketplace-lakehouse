"""SQL helpers shared by the tests that read dbt models as text."""

import re

# SQL line and block comments and Jinja comments: none of them is a filter.
COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/|\{#.*?#\}", re.DOTALL)


def without_comments(sql: str) -> str:
    return COMMENT.sub("", sql)
