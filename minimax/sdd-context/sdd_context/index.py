"""Store current project sources in seekdb and build context from its FTS results."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import re

import pylibseekdb
import pymysql


def words(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


@contextmanager
def connect(directory: Path):
    directory.parent.mkdir(parents=True, exist_ok=True)
    instance = pylibseekdb.open(str(directory))
    try:
        options = dict(instance.connection_options())
        options.setdefault("database", "test")
        connection = pymysql.connect(**options, autocommit=False,
                                     cursorclass=pymysql.cursors.DictCursor)
        try:
            yield connection
        finally:
            connection.close()
    finally:
        instance.close()


def initialize(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("""CREATE TABLE IF NOT EXISTS sdd_project_sources (
            path VARCHAR(512) PRIMARY KEY, kind VARCHAR(16) NOT NULL,
            sha256 CHAR(64) NOT NULL, body LONGTEXT NOT NULL, searchable_text LONGTEXT NOT NULL)""")
        cursor.execute("""SELECT COUNT(*) AS n FROM information_schema.statistics
            WHERE table_schema=DATABASE() AND table_name='sdd_project_sources'
            AND index_name='sdd_sources_fts'""")
        if cursor.fetchone()["n"] == 0:
            cursor.execute("CREATE FULLTEXT INDEX sdd_sources_fts ON sdd_project_sources(searchable_text) WITH PARSER SPACE")
    connection.commit()


def ingest(root: Path, directory: Path) -> dict:
    records = []
    for folder, kind, pattern in [("specs", "spec", "*.md"), ("before", "code", "*.py"), ("tests", "test", "*.py")]:
        for path in sorted((root / folder).rglob(pattern)):
            body = path.read_text(encoding="utf-8")
            name = path.relative_to(root.parent).as_posix()
            records.append((name, kind, hashlib.sha256(body.encode()).hexdigest(), body, words(body)))
    if {row[1] for row in records} != {"spec", "code", "test"}:
        raise ValueError("Import requires specification, code and test sources")
    with connect(directory) as connection:
        initialize(connection)
        with connection.cursor() as cursor:
            # This is a full project snapshot: remove stale versions and deleted paths together.
            cursor.execute("DELETE FROM sdd_project_sources")
            cursor.executemany("INSERT INTO sdd_project_sources VALUES (%s,%s,%s,%s,%s)", records)
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION() AS version")
            version = cursor.fetchone()["version"]
    return {"operation": "ingest", "database": version,
            "sources": [{"path": r[0], "kind": r[1], "sha256": r[2]} for r in records]}


def retrieve(directory: Path, query: str) -> dict:
    sql = """SELECT path, kind, sha256, body,
        MATCH(searchable_text) AGAINST (%s) AS score
        FROM sdd_project_sources WHERE MATCH(searchable_text) AGAINST (%s)
        ORDER BY score DESC, path LIMIT %s"""
    terms = words(query)
    if not terms:
        raise ValueError("Task must contain searchable words")
    with connect(directory) as connection:
        initialize(connection)
        with connection.cursor() as cursor:
            cursor.execute(sql, (terms, terms, 12))
            sources = list(cursor.fetchall())
    for source in sources:
        source["score"] = float(source["score"])
        source["line_start"] = 1
        source["line_end"] = len(source["body"].splitlines())
    return {"sql": sql, "parameters": [terms, terms, 12], "sources": sources}
