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

"""Bounded reconciliation of Source-driven Family progress at startup."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.persistence.cursors import SourceCursorRepository
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.processing_intents import ArtifactProcessingIntentRepository
from powercontext.builtin.persistence.supervision import ArtifactProcessingFence, ArtifactProcessingLeaseRepository
from powercontext.builtin.persistence.tables import PROFILE_POLICIES_TABLE, SOURCE_JOURNAL_HEADS_TABLE


async def enabled_profile_scopes(connection: AsyncConnection, scope_ids: tuple[str, ...]) -> frozenset[str]:
    """Qualify one bounded automatic page before accepting any invocation.

    Hold enabled Policy rows through admission so concurrent policy changes
    serialize with the decision. This reads metadata only, before any Worker
    authorization, model construction, or retry state exists for the page.
    """

    if not scope_ids:
        return frozenset()
    table = PROFILE_POLICIES_TABLE
    rows = await connection.scalars(
        select(table.c.scope_id)
        .where(table.c.scope_id.in_(scope_ids), table.c.generation_enabled.is_(True))
        .with_for_update()
    )
    return frozenset(rows)


class SourceProcessingPendingProvider:
    """Inspect journal metadata, never Source bodies, prompts, or models."""

    def __init__(self, database: AsyncDatabase, binding_name: str, artifact_family: str) -> None:
        self._database = database
        self._binding = binding_name
        self._family = artifact_family

    async def reconcile(self, after_scope_id: str | None, limit: int, *, fence: ArtifactProcessingFence) -> str | None:
        heads = SOURCE_JOURNAL_HEADS_TABLE
        statement = select(heads.c.scope_id, heads.c.position).order_by(heads.c.scope_id).limit(limit)
        if after_scope_id is not None:
            statement = statement.where(heads.c.scope_id > after_scope_id)
        if self._family == "profile":
            statement = statement.join(PROFILE_POLICIES_TABLE, PROFILE_POLICIES_TABLE.c.scope_id == heads.c.scope_id)
            statement = statement.where(PROFILE_POLICIES_TABLE.c.generation_enabled.is_(True))
        async with self._database.transaction() as connection:
            await ArtifactProcessingLeaseRepository().require_fence(connection, fence)
            rows = (await connection.execute(statement)).all()
            intents = ArtifactProcessingIntentRepository()
            cursors = SourceCursorRepository()
            for scope, high in rows:
                cursor = await cursors.load(connection, scope, self._binding)
                if int(high) <= (0 if cursor is None else cursor.cursor.sequence):
                    continue
                intent = await intents.load(connection, scope, self._binding, for_update=True)
                if intent is None or intent.dirty_generation == intent.clean_generation:
                    await intents.mark_dirty(connection, scope, self._binding)
        return str(rows[-1][0]) if len(rows) == limit else None


async def count_due_scopes(
    connection: AsyncConnection, binding_name: str, threshold: int
) -> frozenset[str]:
    """Scopes whose new journal entries since the last committed cursor reach threshold.

    The count reads only persisted journal identity: the gap between a scope's
    latest journal head and the cursor last committed for ``binding_name``. A
    duplicated capture or a receipt trust upgrade reuses an existing journal entry,
    so neither inflates the count; a lineage-only journal entry still occupies a
    slot and therefore participates in the trigger, exactly as the product spec
    requires. The returned set is the source of truth for count-based admission,
    independent of the boolean dirty flag used by the time-based path.
    """

    if threshold < 1:
        return frozenset()
    heads = SOURCE_JOURNAL_HEADS_TABLE
    # A scope can only be count-due when its journal head already reaches the
    # threshold; pending never exceeds the head because the cursor starts at 0
    # and only advances, so this WHERE is a safe pre-filter.
    statement = select(heads.c.scope_id, heads.c.position).where(heads.c.position >= threshold)
    rows = (await connection.execute(statement)).mappings()
    head_by_scope: dict[str, int] = {}
    for row in rows:
        head_by_scope[str(row["scope_id"])] = int(row["position"])
    if not head_by_scope:
        return frozenset()
    cursors = await SourceCursorRepository().load_many(connection, tuple(head_by_scope), binding_name)
    due: set[str] = set()
    for scope_id, head in head_by_scope.items():
        cursor = cursors.get(scope_id)
        sequence: int = 0 if cursor is None else cursor.cursor.sequence
        if head - sequence >= threshold:
            due.add(scope_id)
    return frozenset(due)
