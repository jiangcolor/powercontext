# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
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

"""Synchronous wrapper for PaperStore to use with Flask."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from paper_artifacts import Paper, PaperContent, PaperQuery, PaperSearchResult
from paper_store import PaperStore


class SyncPaperStore:
    """Synchronous interface to PaperStore for Flask routes."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._store: PaperStore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create event loop."""
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop

    def _run_async(self, coro):
        """Run async coroutine synchronously."""
        loop = self._get_loop()
        return loop.run_until_complete(coro)

    async def _get_store(self) -> PaperStore:
        """Get or create paper store."""
        if self._store is None:
            self._store_cm = PaperStore.open(self.db_path)
            self._store = await self._store_cm.__aenter__()
        return self._store

    def init_db(self):
        """Initialize the database (called at startup)."""
        self._run_async(self._get_store())

    def save_paper(self, paper: Paper) -> None:
        """Save a paper."""
        async def _save():
            store = await self._get_store()
            await store.save_paper(paper)
        self._run_async(_save())

    def get_paper(self, paper_id: str) -> Paper | None:
        """Get a paper by ID."""
        async def _get():
            store = await self._get_store()
            return await store.get_paper(paper_id)
        return self._run_async(_get())

    def list_papers(self, cluster: str | None = None, is_relevant: bool | None = None) -> list[Paper]:
        """List papers with optional filters."""
        async def _list():
            store = await self._get_store()
            return await store.list_papers(cluster=cluster, is_relevant=is_relevant)
        return self._run_async(_list())

    def search_papers(self, query: PaperQuery) -> list[PaperSearchResult]:
        """Search papers."""
        async def _search():
            store = await self._get_store()
            return await store.search_papers(query)
        return self._run_async(_search())

    def delete_paper(self, paper_id: str) -> None:
        """Delete a paper."""
        async def _delete():
            store = await self._get_store()
            await store.delete_paper(paper_id)
        self._run_async(_delete())

    def get_clusters(self) -> list[str]:
        """Get all distinct clusters."""
        async def _get():
            store = await self._get_store()
            return await store.get_clusters()
        return self._run_async(_get())

    def update_paper_cluster(self, paper_id: str, cluster: str) -> None:
        """Update paper's cluster."""
        async def _update():
            store = await self._get_store()
            await store.update_paper_cluster(paper_id, cluster)
        self._run_async(_update())

    def update_paper_relevance(self, paper_id: str, is_relevant: bool) -> None:
        """Update paper's relevance flag."""
        async def _update():
            store = await self._get_store()
            await store.update_paper_relevance(paper_id, is_relevant)
        self._run_async(_update())

    def batch_update_clusters(self, cluster_map: dict[str, str]) -> None:
        """Batch update paper clusters."""
        async def _update():
            store = await self._get_store()
            for paper_id, cluster in cluster_map.items():
                await store.update_paper_cluster(paper_id, cluster)
        self._run_async(_update())

    def get_paper_count(self, cluster: str | None = None, is_relevant: bool | None = None) -> int:
        """Get paper count with optional filters."""
        papers = self.list_papers(cluster=cluster, is_relevant=is_relevant)
        return len(papers)

    def find_duplicate(self, title: str) -> Paper | None:
        """Find a paper with similar title."""
        papers = self.list_papers()
        title_lower = title.lower().strip()

        for paper in papers:
            existing_title = paper.content.title.lower().strip()
            if existing_title == title_lower:
                return paper
            if len(title_lower) >= 10 and len(existing_title) >= 10:
                if title_lower in existing_title or existing_title in title_lower:
                    return paper
        return None

    def is_paper_relevant(self, paper: Paper, interests: str, keywords: str) -> bool:
        """Check if paper matches user's research interests."""
        if not interests and not keywords:
            return False

        text = f"{paper.content.title} {paper.content.abstract or ''} {paper.content.methods or ''}".lower()
        interests_lower = interests.lower()
        keywords_lower = keywords.lower()

        if interests_lower:
            for interest in interests_lower.split(","):
                interest = interest.strip()
                if interest and interest in text:
                    return True

        if keywords_lower:
            for keyword in keywords_lower.split(","):
                keyword = keyword.strip()
                if keyword and keyword in text:
                    return True

        return False

    def mark_paper_read(self, paper_id: str) -> None:
        """Mark a paper as read (stub - not implemented in powercontext yet)."""
        pass

    def get_profile(self):
        """Get user profile (stub - returns empty profile)."""
        from dataclasses import dataclass

        @dataclass
        class UserProfile:
            research_interests: str = ""
            focus_keywords: str = ""
            read_papers: list[str] = None

            def __post_init__(self):
                if self.read_papers is None:
                    self.read_papers = []

        return UserProfile()

    def save_profile(self, profile) -> None:
        """Save user profile (stub - not persisted yet)."""
        pass
