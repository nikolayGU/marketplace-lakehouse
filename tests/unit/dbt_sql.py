"""SQL helpers shared by the tests that read dbt models as text."""

import re

# SQL line and block comments and Jinja comments: none of them is a filter.
COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/|\{#.*?#\}", re.DOTALL)


def without_comments(sql: str) -> str:
    return COMMENT.sub("", sql)


def output_columns(sql: str) -> set[str]:
    """Names of the columns of the last top-level `select` of a model.

    Each item of the select list is named by the identifier after its last `as`, else by its last
    identifier (so `i.order_id` is `order_id`). Not a SQL parser: it relies on the model style of
    this repo (one select list, items separated by top-level commas).
    """
    sql = re.sub(r"'[^']*'", "''", without_comments(sql))
    depth, selects, parts = 0, [], []
    for match in re.finditer(r"\bselect\b|\bfrom\b|\(|\)|,", sql, flags=re.IGNORECASE):
        token = match.group().lower()
        if token == ")":
            depth -= 1
        if depth == 0 and token == "select":
            selects.append(match.end())
        if token == "(":
            depth += 1
    start = selects[-1]
    depth, item_start = 0, start
    for match in re.finditer(r"\bfrom\b|\(|\)|,", sql[start:], flags=re.IGNORECASE):
        token = match.group().lower()
        if token == ")":
            depth -= 1
        if depth == 0 and token in {",", "from"}:
            parts.append(sql[item_start : start + match.start()])
            item_start = start + match.end()
            if token == "from":
                break
        if token == "(":
            depth += 1
    names = set()
    for part in parts:
        part = re.sub(r"^\s*distinct\b", "", part.strip(), flags=re.IGNORECASE)
        found = re.search(r"\bas\s+(\w+)\s*$", part, flags=re.IGNORECASE) or re.search(
            r"(\w+)\s*$", part
        )
        if found:
            names.add(found.group(1).lower())
    return names
