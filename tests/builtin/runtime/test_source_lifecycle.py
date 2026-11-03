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

from __future__ import annotations

import pytest
from pydantic import ValidationError

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryInput, MemoryService
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.records import ArtifactWrite
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    SearchTopicMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError, SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceRef


def config(path):
    return BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{path / 'lifecycle.db'}"))


def event(*, sequence=1, available=False, reason="withdraw"):
    return SourceLifecycleEvent(node_id="z-root", revision=3, sequence=sequence, available=available, reason=reason)


async def create_scope(runtime, key="test"):
    assert runtime.scopes is not None
    scope = await runtime.scopes.create(ScopeDraft(title=key, summary="Evidence DAG", idempotency_key=key))
    service = runtime.lifecycle.for_scope(scope.scope_id)
    receipt = await runtime.sources.for_scope(scope.scope_id).capture(
        CaptureSource(source_id="original", content="evidence", metadata={})
    )
    await service.register_source("z-root", receipt.source_ref, revision=3)
    return scope.scope_id, service, receipt.source_ref


async def memory_node(runtime, scope, service, node_id, parents=("z-root",)):
    result = await runtime.memory.for_scope(scope).remember(
        RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"{node_id} reliable evidence"),))
    )
    assert result.entry is not None
    await service.register_memory(node_id, result.entry.citation, parents=parents, policy="all")
    return result.entry.citation


@pytest.mark.asyncio
async def test_full_event_identity_and_registration_conflicts_survive_restart(tmp_path):
    settings = config(tmp_path)
    async with open_builtin_runtime(settings) as runtime:
        scope, service, ref = await create_scope(runtime)
        citation = await memory_node(runtime, scope, service, "fact")
        await service.register_source("z-root", ref, revision=3)
        with pytest.raises(SourceLifecycleError):
            await service.register_source("z-root", ref, revision=4)
        with pytest.raises(SourceLifecycleError):
            await service.register_memory("fact", citation, parents=("z-root",), policy="any")
        await service.apply(event())
    async with open_builtin_runtime(settings) as runtime:
        service = runtime.lifecycle.for_scope(scope)
        before = (await runtime.memory.for_scope(scope).list()).memory_ref
        with pytest.raises(SourceLifecycleError):
            await service.apply(event(reason="different reason"))
        assert await service.apply(event()) == []
        assert (await runtime.memory.for_scope(scope).list()).memory_ref == before
        assert await service.resolve("fact", purpose="audit") == citation


@pytest.mark.asyncio
async def test_missing_and_cross_scope_references_are_rejected(tmp_path):
    async with open_builtin_runtime(config(tmp_path)) as runtime:
        scope, service, _ = await create_scope(runtime)
        other_scope, other, other_ref = await create_scope(runtime, "other")
        foreign = await memory_node(runtime, other_scope, other, "foreign")
        for ref in (
            SourceRef(source_type="content", source_id="absent"),
            other_ref.model_copy(update={"source_id": "not-here"}),
        ):
            with pytest.raises(SourceLifecycleError):
                await service.register_source("bad", ref, revision=1)
        with pytest.raises(SourceLifecycleError):
            await service.register_memory("bad", foreign, parents=("z-root",), policy="all")
        missing = ArtifactRef(family="topic-memory", artifact_id="missing", revision=1)
        with pytest.raises(SourceLifecycleError):
            await service.register_topic("bad", missing, parents=("z-root",), policy="all")
        citation = await memory_node(runtime, scope, service, "valid")
        with pytest.raises(SourceLifecycleError):
            await service.register_memory(
                "bad", citation.model_copy(update={"entry_version_id": "missing"}), parents=("z-root",), policy="all"
            )
        assert await service.apply(event(available=True)) == ["valid", "z-root"]


@pytest.mark.asyncio
async def test_dependency_order_is_independent_of_persisted_node_names(tmp_path):
    settings = config(tmp_path)
    async with open_builtin_runtime(settings) as runtime:
        scope, service, _ = await create_scope(runtime)
        await memory_node(runtime, scope, service, "b-parent")
        leaf = await memory_node(runtime, scope, service, "a-child", parents=("b-parent",))
    async with open_builtin_runtime(settings) as runtime:
        service = runtime.lifecycle.for_scope(scope)
        assert await service.resolve("a-child", purpose="generation") == leaf
        assert await service.apply(event()) == []
        assert await service.apply(event(sequence=2, available=True)) == ["a-child", "b-parent", "z-root"]
        assert all(record.state == "active" for record in (await runtime.memory.for_scope(scope).list()).entries)


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after_restart", [False, True])
async def test_interrupted_propagation_retries_after_restart_without_body_revisions(
    tmp_path, monkeypatch, retry_after_restart
):
    settings = config(tmp_path)
    async with open_builtin_runtime(settings) as runtime:
        scope, service, _ = await create_scope(runtime)
        first = await memory_node(runtime, scope, service, "first")
        second = await memory_node(runtime, scope, service, "second")
        original = MemoryService.forget
        calls = 0

        async def fail_second(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("interrupted native write")  # noqa: TRY003
            return await original(self, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(MemoryService, "forget", fail_second)
            with pytest.raises(RuntimeError, match="interrupted"):
                await service.apply(event())
        states = (await runtime.memory.for_scope(scope).list(include_inactive=True)).entries
        assert {record.state for record in states} == {"active", "inactive"}
        if not retry_after_restart:
            assert await service.apply(event()) == []
            assert all(
                record.state == "inactive"
                for record in (await runtime.memory.for_scope(scope).list(include_inactive=True)).entries
            )
    async with open_builtin_runtime(settings) as runtime:
        service = runtime.lifecycle.for_scope(scope)
        assert await service.apply(event()) == []
        memory = runtime.memory.for_scope(scope)
        records = (await memory.list(include_inactive=True)).entries
        assert len(records) == 2 and all(record.state == "inactive" for record in records)
        before = (await memory.list()).memory_ref
        assert await service.apply(event()) == []
        assert (await memory.list()).memory_ref == before
        for citation in (first, second):
            assert (
                await memory.get(GetMemoryEntryRequest(citation=citation))
            ).entry.entry_version_id == citation.entry_version_id
        assert not (await memory.search(SearchMemoryRequest(query="reliable evidence", mode="fts"))).hits
        await service.apply(event(sequence=2, available=True))
        assert len((await memory.list()).entries) == 2


@pytest.mark.asyncio
async def test_multiple_handles_do_not_overwrite_graph_and_scopes_are_isolated(tmp_path):
    async with open_builtin_runtime(config(tmp_path)) as runtime:
        scope, old_handle, _ = await create_scope(runtime)
        await memory_node(runtime, scope, runtime.lifecycle.for_scope(scope), "fact")
        other_scope, other, _ = await create_scope(runtime, "other")
        other_citation = await memory_node(runtime, other_scope, other, "fact")
        assert await old_handle.apply(event()) == []
        assert await other.resolve("fact", purpose="generation") == other_citation
        with pytest.raises(SourceLifecycleError):
            await runtime.lifecycle.for_scope(scope).resolve("fact", purpose="generation")


@pytest.mark.asyncio
async def test_withdrawn_top_hit_does_not_hide_surviving_topic_at_limit_one(tmp_path):
    async with open_builtin_runtime(config(tmp_path)) as runtime:
        scope, service, _ = await create_scope(runtime)
        receipt = await runtime.sources.for_scope(scope).capture(
            CaptureSource(source_id="survivor", content="independent", metadata={})
        )
        await service.register_source("survivor", receipt.source_ref, revision=1)
        refs = []
        for title in ("alpha", "beta"):
            artifact = await runtime.records.for_scope(scope).create_artifact(
                "topic-memory",
                ArtifactWrite(
                    content={
                        "title": title,
                        "summary": "quartz recovery details",
                        "detail": "quartz recovery independent facts",
                    }
                ),
            )
            refs.append(
                ArtifactRef(family="topic-memory", artifact_id=artifact.artifact_id, revision=artifact.revision)
            )
        topics = runtime.topic_memory.for_scope(scope)
        top = (await topics.search(SearchTopicMemoryRequest(query="quartz recovery", limit=1))).hits[0].artifact_ref
        for index, ref in enumerate(refs):
            await service.register_topic(
                f"topic{index}", ref, parents=("z-root" if ref == top else "survivor",), policy="all"
            )
        await service.apply(event())
        hits = (await topics.search(SearchTopicMemoryRequest(query="quartz recovery", limit=1))).hits
        assert len(hits) == 1 and hits[0].artifact_ref != top
        assert await service.resolve(f"topic{refs.index(top)}", purpose="audit") == top


@pytest.mark.parametrize(
    "field,value", [("revision", True), ("sequence", "1"), ("available", 1), ("node_id", " "), ("reason", " ")]
)
def test_events_validate_fields(field, value):
    with pytest.raises(ValidationError):
        SourceLifecycleEvent.model_validate({**event().model_dump(), field: value})
