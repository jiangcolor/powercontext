#!/usr/bin/env python3
"""Migrate data from old SQLite database to powercontext PaperStore."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from paper_artifacts import Paper, PaperContent
from paper_store import PaperStore


OLD_DB_PATH = Path("data/papers.db")
NEW_DB_PATH = Path("data/papers_powercontext.db")


def read_old_papers() -> list[dict]:
    """Read all papers from the old database."""
    if not OLD_DB_PATH.exists():
        print(f"Old database not found at {OLD_DB_PATH}")
        return []

    conn = sqlite3.connect(str(OLD_DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute("SELECT * FROM papers").fetchall()
        papers = []
        for row in rows:
            paper_dict = dict(row)
            paper_dict["authors"] = json.loads(paper_dict.get("authors", "[]"))
            paper_dict["references"] = json.loads(paper_dict.get("references", "[]"))
            papers.append(paper_dict)
        return papers
    finally:
        conn.close()


def read_old_profile() -> dict | None:
    """Read user profile from the old database."""
    if not OLD_DB_PATH.exists():
        return None

    conn = sqlite3.connect(str(OLD_DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        row = conn.execute("SELECT * FROM user_profiles LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def read_old_relations() -> list[dict]:
    """Read paper relations from the old database."""
    if not OLD_DB_PATH.exists():
        return []

    conn = sqlite3.connect(str(OLD_DB_PATH))
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute("SELECT * FROM paper_relations").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


async def migrate():
    """Run the migration."""
    print("Starting migration from old database to powercontext PaperStore...")

    old_papers = read_old_papers()
    old_profile = read_old_profile()
    old_relations = read_old_relations()

    print(f"Found {len(old_papers)} papers to migrate")
    print(f"Found {len(old_relations)} relations to migrate")
    print(f"User profile: {'found' if old_profile else 'not found'}")

    NEW_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with PaperStore.open(NEW_DB_PATH) as store:
        for i, old_paper in enumerate(old_papers, 1):
            print(f"Migrating paper {i}/{len(old_papers)}: {old_paper.get('title', 'untitled')[:50]}...")

            try:
                created_at = old_paper.get("created_at")
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                elif created_at is None:
                    created_at = datetime.now()

                content = PaperContent(
                    title=old_paper.get("title", "Untitled"),
                    authors=old_paper.get("authors", []),
                    year=old_paper.get("year"),
                    venue=old_paper.get("venue"),
                    abstract=old_paper.get("abstract"),
                    methods=old_paper.get("methods"),
                    contributions=old_paper.get("contributions"),
                    conclusions=old_paper.get("conclusions"),
                    references=old_paper.get("references", []),
                    topic_cluster=old_paper.get("topic_cluster"),
                    pdf_path=old_paper.get("pdf_path"),
                    tags=[],
                    is_relevant=False,
                    created_at=created_at,
                )

                paper = Paper(
                    artifact_id=old_paper["paper_id"],
                    revision=1,
                    content=content,
                )

                await store.save_paper(paper)
            except Exception as e:
                print(f"  Error migrating paper: {e}")

        print(f"\nMigration complete! {len(old_papers)} papers migrated.")
        print(f"New database: {NEW_DB_PATH}")


if __name__ == "__main__":
    asyncio.run(migrate())
