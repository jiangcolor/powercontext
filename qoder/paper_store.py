# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Paper persistence using powercontext's SQLite infrastructure."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    select,
    text,
)

from paper_artifacts import Paper, PaperContent, PaperQuery, PaperSearchResult
from powercontext.builtin.persistence.sqlite.profile import SQLiteConfig, SQLiteProfile


PAPER_METADATA = MetaData()

PAPERS_TABLE = Table(
    "papers",
    PAPER_METADATA,
    Column("paper_id", String(255), primary_key=True),
    Column("revision", Integer, nullable=False, default=1),
    Column("title", Text, nullable=False),
    Column("title_search", Text, nullable=False),
    Column("authors", Text, nullable=False),
    Column("year", Integer),
    Column("venue", String(500)),
    Column("abstract", Text),
    Column("abstract_search", Text),
    Column("methods", Text),
    Column("contributions", Text),
    Column("conclusions", Text),
    Column("references_json", Text, nullable=False, default="[]"),
    Column("topic_cluster", String(255)),
    Column("pdf_path", String(1000)),
    Column("tags_json", Text, nullable=False, default="[]"),
    Column("is_relevant", Integer, nullable=False, default=0),
    Column("embedding", Text),
    Column("created_at", DateTime, nullable=False, default=datetime.now),
    Index("idx_papers_cluster", "topic_cluster"),
    Index("idx_papers_relevant", "is_relevant"),
    Index("idx_papers_year", "year"),
)


class PaperStore:
    """Async paper store using powercontext's SQLite profile."""

    def __init__(self, profile: SQLiteProfile) -> None:
        self.profile = profile
        self.database = profile.database

    @classmethod
    @asynccontextmanager
    async def open(cls, db_path: str | Path) -> AsyncIterator[PaperStore]:
        """Open a paper store at the given database path."""
        config = SQLiteConfig(url=f"sqlite+aiosqlite:///{db_path}")
        async with SQLiteProfile.open(config, tables=(PAPERS_TABLE,), load_vector_extension=True) as profile:
            store = cls(profile)
            await store._ensure_fts_tables()
            yield store

    async def _ensure_fts_tables(self):
        """Create FTS5 virtual tables for full-text search."""
        async with self.database.transaction() as conn:
            await conn.exec_driver_sql("""
                CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
                    paper_id,
                    title,
                    abstract,
                    methods,
                    contributions,
                    tokenize='unicode61'
                )
            """)

    async def save_paper(self, paper: Paper) -> None:
        """Save or update a paper artifact."""
        content = paper.content
        paper_id = paper.artifact_id
        revision = paper.revision

        title_search = content.title.lower()
        abstract_search = (content.abstract or "").lower()

        async with self.database.transaction() as conn:
            await conn.execute(
                PAPERS_TABLE.insert().values(
                    paper_id=paper_id,
                    revision=revision,
                    title=content.title,
                    title_search=title_search,
                    authors=json.dumps(content.authors, ensure_ascii=False),
                    year=content.year,
                    venue=content.venue,
                    abstract=content.abstract,
                    abstract_search=abstract_search,
                    methods=content.methods,
                    contributions=content.contributions,
                    conclusions=content.conclusions,
                    references_json=json.dumps(content.references, ensure_ascii=False),
                    topic_cluster=content.topic_cluster,
                    pdf_path=content.pdf_path,
                    tags_json=json.dumps(content.tags, ensure_ascii=False),
                    is_relevant=1 if content.is_relevant else 0,
                    created_at=content.created_at,
                )
            )

            await conn.exec_driver_sql(
                "INSERT INTO papers_fts(paper_id, title, abstract, methods, contributions) VALUES (?, ?, ?, ?, ?)",
                (paper_id, content.title, content.abstract or "", content.methods or "", content.contributions or ""),
            )

    async def get_paper(self, paper_id: str) -> Paper | None:
        """Retrieve a paper by ID."""
        async with self.database.transaction() as conn:
            result = await conn.execute(
                select(PAPERS_TABLE).where(PAPERS_TABLE.c.paper_id == paper_id)
            )
            row = result.fetchone()

        if not row:
            return None

        return self._row_to_paper(row)

    async def list_papers(self, cluster: str | None = None, is_relevant: bool | None = None) -> list[Paper]:
        """List papers with optional filters."""
        query = select(PAPERS_TABLE)
        if cluster:
            query = query.where(PAPERS_TABLE.c.topic_cluster == cluster)
        if is_relevant is not None:
            query = query.where(PAPERS_TABLE.c.is_relevant == (1 if is_relevant else 0))
        query = query.order_by(PAPERS_TABLE.c.created_at.desc())

        async with self.database.transaction() as conn:
            result = await conn.execute(query)
            rows = result.fetchall()

        return [self._row_to_paper(row) for row in rows]

    async def search_papers(self, query: PaperQuery) -> list[PaperSearchResult]:
        """Search papers using FTS, vector, or hybrid mode."""
        if query.mode == "fts":
            return await self._fts_search(query)
        elif query.mode == "vector":
            return await self._vector_search(query)
        else:
            return await self._hybrid_search(query)

    async def _fts_search(self, query: PaperQuery) -> list[PaperSearchResult]:
        """Full-text search using FTS5."""
        search_text = query.text.lower()
        fts_query = text("""
            SELECT paper_id, rank
            FROM papers_fts
            WHERE papers_fts MATCH :query
            ORDER BY rank
            LIMIT :limit
        """)

        async with self.database.transaction() as conn:
            result = await conn.execute(fts_query, {"query": search_text, "limit": query.limit})
            fts_rows = result.fetchall()

        papers = []
        for row in fts_rows:
            paper = await self.get_paper(row[0])
            if paper:
                if query.cluster and paper.content.topic_cluster != query.cluster:
                    continue
                if query.is_relevant is not None and paper.content.is_relevant != query.is_relevant:
                    continue
                papers.append(PaperSearchResult(
                    paper=paper,
                    score=-row[1],
                    matched_by="fts",
                ))

        return papers[:query.limit]

    async def _vector_search(self, query: PaperQuery) -> list[PaperSearchResult]:
        """Vector similarity search (placeholder - requires embedding computation)."""
        return []

    async def _hybrid_search(self, query: PaperQuery) -> list[PaperSearchResult]:
        """Combine FTS and vector search using RRF."""
        fts_results = await self._fts_search(query)
        vector_results = await self._vector_search(query)

        rrf_k = 60
        scores: dict[str, float] = {}
        matched_by: dict[str, str] = {}

        for rank, result in enumerate(fts_results):
            paper_id = result.paper.artifact_id
            scores[paper_id] = scores.get(paper_id, 0) + 1 / (rrf_k + rank + 1)
            matched_by[paper_id] = "hybrid"

        for rank, result in enumerate(vector_results):
            paper_id = result.paper.artifact_id
            scores[paper_id] = scores.get(paper_id, 0) + 1 / (rrf_k + rank + 1)
            matched_by[paper_id] = "hybrid"

        sorted_ids = sorted(scores.keys(), key=lambda pid: scores[pid], reverse=True)

        results = []
        for paper_id in sorted_ids[:query.limit]:
            paper = await self.get_paper(paper_id)
            if paper:
                results.append(PaperSearchResult(
                    paper=paper,
                    score=scores[paper_id],
                    matched_by=matched_by[paper_id],
                ))

        return results

    async def delete_paper(self, paper_id: str) -> None:
        """Delete a paper by ID."""
        async with self.database.transaction() as conn:
            await conn.execute(
                PAPERS_TABLE.delete().where(PAPERS_TABLE.c.paper_id == paper_id)
            )
            await conn.exec_driver_sql(
                "DELETE FROM papers_fts WHERE paper_id = ?", (paper_id,)
            )

    async def get_clusters(self) -> list[str]:
        """Get all distinct topic clusters."""
        async with self.database.transaction() as conn:
            result = await conn.execute(
                select(PAPERS_TABLE.c.topic_cluster).distinct().where(
                    PAPERS_TABLE.c.topic_cluster.isnot(None)
                )
            )
            return [row[0] for row in result.fetchall()]

    async def update_paper_cluster(self, paper_id: str, cluster: str) -> None:
        """Update a paper's topic cluster."""
        async with self.database.transaction() as conn:
            await conn.execute(
                PAPERS_TABLE.update()
                .where(PAPERS_TABLE.c.paper_id == paper_id)
                .values(topic_cluster=cluster)
            )

    async def update_paper_relevance(self, paper_id: str, is_relevant: bool) -> None:
        """Update a paper's relevance flag."""
        async with self.database.transaction() as conn:
            await conn.execute(
                PAPERS_TABLE.update()
                .where(PAPERS_TABLE.c.paper_id == paper_id)
                .values(is_relevant=1 if is_relevant else 0)
            )

    def _row_to_paper(self, row) -> Paper:
        """Convert a database row to a Paper artifact."""
        content = PaperContent(
            title=row.title,
            authors=json.loads(row.authors),
            year=row.year,
            venue=row.venue,
            abstract=row.abstract,
            methods=row.methods,
            contributions=row.contributions,
            conclusions=row.conclusions,
            references=json.loads(row.references_json),
            topic_cluster=row.topic_cluster,
            pdf_path=row.pdf_path,
            tags=json.loads(row.tags_json),
            is_relevant=bool(row.is_relevant),
            created_at=row.created_at,
        )
        return Paper(
            artifact_id=row.paper_id,
            revision=row.revision,
            content=content,
        )
