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

"""Propagate Source availability through one scope's evidence DAG."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from graphlib import TopologicalSorter
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.sources.models import SourceRef

LifecyclePurpose = Literal["generation", "audit"]
LifecyclePolicy = Literal["all", "any"]


class SourceLifecycleError(ValueError):
    """Raised when a lifecycle registration, event, or resolution is invalid."""


class SourceLifecycleEvent(BaseModel):
    """One availability transition addressed to a registered Source."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    revision: Annotated[int, Field(gt=0, strict=True)]
    sequence: Annotated[int, Field(gt=0, strict=True)]
    available: bool = Field(strict=True)
    reason: str = Field(min_length=1)

    @field_validator("node_id", "reason")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("lifecycle text fields must not be blank")  # noqa: TRY003
        return value


@dataclass
class _Node:
    kind: str
    ref: Any
    parents: tuple[str, ...]
    policy: str
    revision: int | None = None
    sequence: int = 0
    available: bool = True
    event: SourceLifecycleEvent | None = None
    pending: bool = False


def active_lifecycle_nodes(nodes: Mapping[str, tuple[str, tuple[str, ...], str, bool]]) -> set[str]:
    """Evaluate the DAG in dependency order, independently of storage row order."""
    active = set()
    for node_id in TopologicalSorter({key: value[1] for key, value in nodes.items()}).static_order():
        kind, parents, policy, available = nodes[node_id]
        supported = (
            available
            if kind == "source"
            else (
                all(parent in active for parent in parents)
                if policy == "all"
                else any(parent in active for parent in parents)
            )
        )
        if supported:
            active.add(node_id)
    return active


class SourceLifecycleService:
    """Track one scope's dependency graph and mirror it onto native Memory state."""

    def __init__(self, runtime: Any, scope_id: str) -> None:
        self._runtime = runtime
        self.scope_id = scope_id
        self._nodes: dict[str, _Node] = {}

    async def register_source(self, node_id: str, source_ref: SourceRef, /, *, revision: int) -> None:
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("register_source requires a captured SourceRef")  # noqa: TRY003
        if type(revision) is not int or revision < 1:
            raise SourceLifecycleError("revision must be a positive integer")  # noqa: TRY003
        await self._register(_Node("source", source_ref, (), "all", revision), node_id, ())

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, /, *, parents: tuple[str, ...], policy: str
    ) -> None:
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("register_memory requires a readable MemoryCitation")  # noqa: TRY003
        await self._register(_Node("memory", citation, tuple(parents), policy), node_id, parents)

    async def register_topic(
        self, node_id: str, artifact_ref: ArtifactRef, /, *, parents: tuple[str, ...], policy: str
    ) -> None:
        if not isinstance(artifact_ref, ArtifactRef):
            raise SourceLifecycleError("register_topic requires a readable ArtifactRef")  # noqa: TRY003
        await self._register(_Node("topic", artifact_ref, tuple(parents), policy), node_id, parents)

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            await self._ensure_loaded()
            node = self._nodes.get(event.node_id)
            if node is None or node.kind != "source":
                raise SourceLifecycleError(f"unknown lifecycle source {event.node_id!r}")  # noqa: TRY003
            if node.revision != event.revision:
                raise SourceLifecycleError("revision-mismatch")
            if event.sequence < node.sequence:
                raise SourceLifecycleError("sequence-stale")
            if event.sequence == node.sequence:
                if node.event is not None and node.event != event:
                    raise SourceLifecycleError("sequence-conflict")
                if node.available != event.available:
                    raise SourceLifecycleError("sequence-conflict")
                if not node.pending and node.event is not None:
                    return sorted(self._active_nodes())
            # Save the full event and its desired state before touching Memory.
            # A failed/cancelled propagation is a durable intent, recoverable by a
            # fresh service or process. Clearing pending is the completion marker.
            node.event = event
            node.sequence = event.sequence
            node.available = event.available
            node.pending = True
            await self._persist()
            await self._sync()
            node.pending = False
            await self._persist()
            return sorted(self._active_nodes())

    async def resolve(self, node_id: str, /, *, purpose: str) -> Any:
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            await self._ensure_loaded()
            if purpose not in {"generation", "audit"}:
                raise SourceLifecycleError(f"unknown lifecycle purpose {purpose!r}")  # noqa: TRY003
            node = self._nodes.get(node_id)
            if node is None:
                raise SourceLifecycleError(f"unknown lifecycle node {node_id!r}")  # noqa: TRY003
            if purpose == "generation" and not self._is_available(node_id):
                raise SourceLifecycleError(f"node {node_id!r} has no supporting evidence")  # noqa: TRY003
            return node.ref

    def _is_available(self, node_id: str) -> bool:
        return node_id in self._active_nodes()

    def _active_nodes(self) -> set[str]:
        return active_lifecycle_nodes({
            key: (node.kind, node.parents, node.policy, node.available) for key, node in self._nodes.items()
        })

    async def _register(self, node: _Node, node_id: str, parents: tuple[str, ...]) -> None:
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            await self._ensure_loaded()
            self._validate_registration(node, node_id, parents)
            existing = self._nodes.get(node_id)
            if existing is not None and (
                existing.kind,
                existing.parents,
                existing.policy,
                existing.ref,
                existing.revision,
            ) != (
                node.kind,
                node.parents,
                node.policy,
                node.ref,
                node.revision,
            ):
                raise SourceLifecycleError(f"lifecycle node {node_id!r} is already bound differently")  # noqa: TRY003
            await self._validate_reference(node)
            if existing is None:
                self._nodes[node_id] = node
                await self._persist()
            # Repeating a registration also repairs an interrupted initial sync.
            await self._sync()

    def _validate_registration(self, node: _Node, node_id: str, parents: tuple[str, ...]) -> None:
        if not isinstance(node_id, str) or not node_id.strip():
            raise SourceLifecycleError("node-id-invalid")
        if node.policy not in {"all", "any"}:
            raise SourceLifecycleError("policy-invalid")
        if node.kind != "source" and not parents:
            raise SourceLifecycleError("parents-empty")
        if any(not isinstance(parent, str) or not parent.strip() for parent in parents):
            raise SourceLifecycleError("parent-id-invalid")
        if len(set(parents)) != len(parents):
            raise SourceLifecycleError("parents-duplicate")
        for parent in parents:
            if parent == node_id:
                raise SourceLifecycleError("parent-self")
            if parent not in self._nodes:
                raise SourceLifecycleError(f"lifecycle parent {parent!r} is not registered")  # noqa: TRY003

    async def _validate_reference(self, node: _Node) -> None:
        from powercontext.builtin.runtime.models import GetMemoryEntryRequest
        from powercontext.sources.models import SourceMaterialization

        try:
            if node.kind == "source":
                async with self._runtime._context(self.scope_id) as context:
                    entries = await context.sources.journal.entries()
                if not any(
                    entry.source_ref == node.ref and entry.source.materialization == SourceMaterialization.CAPTURED
                    for entry in entries
                ):
                    raise SourceLifecycleError("source-not-captured")  # noqa: TRY301
            elif node.kind == "memory":
                await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=node.ref))
                async with self._runtime._context(self.scope_id) as context:
                    _, entries = await context.artifacts.memory.head_entries(context.artifacts.memory_artifact_id)
                if not any(
                    entry.entry_id == node.ref.entry_id and entry.entry_version_id == node.ref.entry_version_id
                    for entry in entries
                ):
                    raise SourceLifecycleError("memory-version-not-current")  # noqa: TRY301
            else:
                if node.ref.family != "topic-memory":
                    raise SourceLifecycleError("topic-family-invalid")  # noqa: TRY301
                await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                    node.ref.family, node.ref.artifact_id, node.ref.revision
                )
        except SourceLifecycleError:
            raise
        except Exception as error:
            raise SourceLifecycleError("reference-unreadable") from error

    async def _sync(self) -> None:
        active = self._active_nodes()
        memories = [(nid, node) for nid, node in self._nodes.items() if node.kind == "memory"]
        if not memories:
            return
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            artifact_id = context.artifacts.memory_artifact_id
            for node_id, node in memories:
                memory, entries = await service.head_entries(artifact_id)
                entry = next((item for item in entries if item.entry_id == node.ref.entry_id), None)
                if entry is None or entry.entry_version_id != node.ref.entry_version_id:
                    raise SourceLifecycleError("memory-version-mismatch")
                # forget/reactivate are idempotent and never create a new revision
                # when the entry already carries the requested state.
                if node_id in active:
                    await service.reactivate(memory, entries=(entry,), reason="lifecycle-restore")
                else:
                    await service.forget(memory, entries=(entry,), reason="lifecycle-withdraw")

    def _provider(self) -> Any:
        provider = getattr(self._runtime, "_provider", None)
        if provider is None or not hasattr(provider, "lifecycle_load_nodes"):
            return None
        return provider

    async def _ensure_loaded(self) -> None:
        # Handles can coexist even in the specified single-writer scope. Never
        # let an old service snapshot overwrite another handle's registrations.
        provider = self._provider()
        if provider is None:
            raise SourceLifecycleError("persistent-provider-required")
        self._nodes = {
            row["node_id"]: self._row_to_node(row) for row in await provider.lifecycle_load_nodes(self.scope_id)
        }

    async def _persist(self) -> None:
        rows = [self._node_to_row(nid, node) for nid, node in self._nodes.items()]
        await self._provider().lifecycle_upsert_nodes(self.scope_id, rows)

    @staticmethod
    def _node_to_row(node_id: str, node: _Node) -> dict[str, Any]:
        return {
            "node_id": node_id,
            "kind": node.kind,
            # Source reference envelopes add a durable event/completion marker without
            # changing the existing table schema. Legacy bare references still load.
            "ref_json": json.dumps({
                "reference": node.ref.model_dump(mode="json"),
                "event": None if node.event is None else node.event.model_dump(mode="json"),
                "pending": node.pending,
            })
            if node.kind == "source"
            else node.ref.model_dump_json(),
            "parents_json": json.dumps(list(node.parents)),
            "policy": node.policy,
            "revision": node.revision,
            "sequence": node.sequence,
            "available": node.available,
        }

    @staticmethod
    def _row_to_node(row: Mapping[str, Any]) -> _Node:
        kind = row["kind"]
        payload = json.loads(row["ref_json"])
        envelope = payload if kind == "source" and "reference" in payload else {}
        reference = envelope.get("reference", payload)
        ref_type = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[kind]
        node = _Node(
            kind,
            ref_type.model_validate(reference),
            tuple(json.loads(row["parents_json"])),
            row["policy"],
            row.get("revision"),
        )
        node.sequence = row.get("sequence", 0)
        node.available = row.get("available", True)
        node.event = SourceLifecycleEvent.model_validate(envelope["event"]) if envelope.get("event") else None
        node.pending = envelope.get("pending", False)
        return node


class LifecycleApplication:
    """Expose per-scope lifecycle services through the Runtime boundary."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def for_scope(self, scope_id: str) -> SourceLifecycleService:
        return SourceLifecycleService(self._runtime, scope_id)


__all__ = [
    "LifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
    "SourceLifecycleService",
]
