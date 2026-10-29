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
from pathlib import Path
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


class _Node:
    __slots__ = ("kind", "ref", "parents", "policy", "revision", "sequence", "available")

    def __init__(self, kind: str, ref: Any, parents: tuple[str, ...], policy: str, revision: int | None = None) -> None:
        self.kind = kind
        self.ref = ref
        self.parents = parents
        self.policy = policy
        self.revision = revision
        self.sequence = 0
        self.available = True


class SourceLifecycleService:
    """Track one scope's dependency graph and mirror it onto native Memory state."""

    def __init__(self, runtime: Any, scope_id: str) -> None:
        self._runtime = runtime
        self.scope_id = scope_id
        self._nodes: dict[str, _Node] = {}
        self._loaded = False

    async def register_source(self, node_id: str, source_ref: SourceRef, /, *, revision: int) -> None:
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("register_source requires a captured SourceRef")
        if type(revision) is not int or revision < 1:
            raise SourceLifecycleError("revision must be a positive integer")
        await self._register(_Node("source", source_ref, (), "all", revision), node_id, ())

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, /, *, parents: tuple[str, ...], policy: str
    ) -> None:
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("register_memory requires a readable MemoryCitation")
        await self._register(_Node("memory", citation, tuple(parents), policy), node_id, parents)

    async def register_topic(
        self, node_id: str, artifact_ref: ArtifactRef, /, *, parents: tuple[str, ...], policy: str
    ) -> None:
        if not isinstance(artifact_ref, ArtifactRef):
            raise SourceLifecycleError("register_topic requires a readable ArtifactRef")
        await self._register(_Node("topic", artifact_ref, tuple(parents), policy), node_id, parents)

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        await self._ensure_loaded()
        node = self._nodes.get(event.node_id)
        if node is None or node.kind != "source":
            raise SourceLifecycleError(f"unknown lifecycle source {event.node_id!r}")
        if node.revision != event.revision:
            raise SourceLifecycleError("lifecycle event revision does not match the registered source")
        if event.sequence < node.sequence:
            raise SourceLifecycleError("lifecycle event sequence must be monotonic")
        if event.sequence == node.sequence:
            if node.available == event.available:
                return sorted(self._active_nodes())
            raise SourceLifecycleError("lifecycle event sequence was reused with different content")
        node.sequence = event.sequence
        node.available = event.available
        await self._sync()
        await self._persist()
        return sorted(self._active_nodes())

    async def resolve(self, node_id: str, /, *, purpose: str) -> Any:
        await self._ensure_loaded()
        if purpose not in {"generation", "audit"}:
            raise SourceLifecycleError(f"unknown lifecycle purpose {purpose!r}")
        node = self._nodes.get(node_id)
        if node is None:
            raise SourceLifecycleError(f"unknown lifecycle node {node_id!r}")
        if purpose == "generation" and not self._is_available(node_id):
            raise SourceLifecycleError(f"node {node_id!r} has no supporting evidence")
        return node.ref

    def _is_available(self, node_id: str) -> bool:
        return node_id in self._active_nodes()

    def _active_nodes(self) -> set[str]:
        active = {nid for nid, node in self._nodes.items() if node.kind == "source" and node.available}
        for nid, node in self._nodes.items():
            if node.kind == "source":
                continue
            support = [parent in active for parent in node.parents]
            if (node.policy == "all" and all(support)) or (node.policy == "any" and any(support)):
                active.add(nid)
        return active

    async def _register(self, node: _Node, node_id: str, parents: tuple[str, ...]) -> None:
        await self._ensure_loaded()
        if not isinstance(node_id, str) or not node_id.strip():
            raise SourceLifecycleError("lifecycle node ids must be non-blank")
        if node.policy not in {"all", "any"}:
            raise SourceLifecycleError("lifecycle policy must be 'all' or 'any'")
        if node.kind != "source" and not parents:
            raise SourceLifecycleError("derived lifecycle nodes require at least one parent")
        if len(set(parents)) != len(parents):
            raise SourceLifecycleError("lifecycle parents must not repeat")
        for parent in parents:
            if parent == node_id:
                raise SourceLifecycleError("lifecycle nodes cannot depend on themselves")
            if parent not in self._nodes:
                raise SourceLifecycleError(f"lifecycle parent {parent!r} is not registered")
        existing = self._nodes.get(node_id)
        if existing is not None:
            if existing.kind == node.kind and existing.parents == node.parents and existing.ref == node.ref:
                return
            raise SourceLifecycleError(f"lifecycle node {node_id!r} is already bound differently")
        self._nodes[node_id] = node
        await self._sync()
        await self._persist()

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
                if entry is None:
                    continue
                # forget/reactivate are idempotent and never create a new revision
                # when the entry already carries the requested state.
                if node_id in active:
                    await service.reactivate(memory, entries=(entry,), reason="lifecycle-restore")
                else:
                    await service.forget(memory, entries=(entry,), reason="lifecycle-withdraw")

    def _path(self) -> Path | None:
        url = getattr(getattr(self._runtime, "_config", None), "database", None)
        raw = getattr(url, "url", "") or ""
        if ":///" not in raw:
            return None
        target = raw.split("///", 1)[1]
        if not target or target == ":memory:":
            return None
        return Path(target + ".lifecycle.json")

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        path = self._path()
        if path is not None and path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                payload = {}
            for node_id, item in payload.get("nodes", {}).items():
                kind = item["kind"]
                ref = _decode_ref(kind, item["ref"])
                node = _Node(kind, ref, tuple(item["parents"]), item["policy"], item.get("revision"))
                node.sequence = item.get("sequence", 0)
                node.available = item.get("available", True)
                self._nodes[node_id] = node
        self._loaded = True

    async def _persist(self) -> None:
        path = self._path()
        if path is None:
            return
        payload = {
            "nodes": {
                nid: {
                    "kind": node.kind,
                    "ref": node.ref.model_dump(mode="json"),
                    "parents": list(node.parents),
                    "policy": node.policy,
                    "revision": node.revision,
                    "sequence": node.sequence,
                    "available": node.available,
                }
                for nid, node in self._nodes.items()
            }
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _decode_ref(kind: str, payload: dict[str, Any]) -> Any:
    if kind == "source":
        return SourceRef.model_validate(payload)
    if kind == "memory":
        return MemoryCitation.model_validate(payload)
    return ArtifactRef.model_validate(payload)


async def _entry_for_citation(service: Any, artifact_id: str, citation: MemoryCitation) -> Any:
    memory, entries = await service.head_entries(artifact_id)
    for entry in entries:
        if entry.entry_id == citation.entry_id:
            return entry
    return None


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
