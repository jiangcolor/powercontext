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

import json

import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY
from powercontext.builtin.scope import ScopeDraft


def group(text, *, scope="scope", artifact="memory"):
    ref = ArtifactRef(family="memory", artifact_id=artifact, revision=1)
    hit = MemoryHit(
        memory_ref=ref, entry_id="entry", entry_version_id="version", text=text, score=1.0, matched_by=("fts",)
    )
    return PreparedMemoryCandidates(scope_id=scope, memory_ref=ref, hits=(hit,))


def build(groups, query, max_bytes=1800, selection=True):
    return PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query=query, max_bytes=max_bytes, evidence_selection=selection),
        current_scope_id="scope",
        memory_candidates=groups,
    )


def assert_wire(result, groups, budget):
    content = result.context.content or ""
    assert result.context.content_bytes == len(content.encode("utf-8")) <= budget
    if not content:
        assert not result.fragments and not result.origins
        return
    assert content.startswith(TRUST_POLICY)
    assert "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n" in content
    assert content.endswith("END_POWERCONTEXT_PREPARED_CONTEXT_V1")
    items = json.loads(content.splitlines()[-2])["items"]
    assert len(items) == len(result.fragments) == len(result.origins)
    for item, fragment, origin in zip(items, result.fragments, result.origins, strict=True):
        assert origin == fragment.address
        assert type(fragment.start) is int and type(fragment.end) is int
        original = next(
            hit.text
            for g in groups
            for hit in g.hits
            if g.scope_id == fragment.address.memory.scope_id
            and hit.memory_ref == fragment.address.memory.artifact
            and hit.entry_id == fragment.address.entry_id
            and hit.entry_version_id == fragment.address.entry_version_id
        )
        assert 0 <= fragment.start < fragment.end <= len(original)
        assert item["content"] == fragment.text == original[fragment.start : fragment.end]
        assert item["start"] == fragment.start and item["end"] == fragment.end
        assert item["citation"] == {
            "scope_id": fragment.address.memory.scope_id,
            "memory_ref": fragment.address.memory.artifact.model_dump(mode="json"),
            "entry_id": fragment.address.entry_id,
            "entry_version_id": fragment.address.entry_version_id,
        }


def test_multiple_adjacent_evidence_sentences_are_retained_together():
    text = (
        "Administrative background. " * 40
        + "Cobalt exposure reduces neuron viability. Cobalt treatment increases cellular inflammation. Unrelated appendix."
    )
    groups = (group(text),)
    result = build(groups, "Cobalt exposure viability cellular inflammation")
    delivered = " ".join(fragment.text for fragment in result.fragments)
    assert "reduces neuron viability." in delivered and "increases cellular inflammation." in delivered
    assert_wire(result, groups, 1800)


def test_disjoint_evidence_avoids_a_long_unrelated_gap():
    text = (
        "Cobalt exposure reduces viability. "
        + "Administrative records occupy storage. " * 70
        + "Cobalt treatment increases inflammation."
    )
    groups = (group(text),)
    result = build(groups, "Cobalt viability inflammation", max_bytes=1400)
    assert len(result.fragments) == 2
    assert any("viability" in fragment.text for fragment in result.fragments)
    assert any("inflammation" in fragment.text for fragment in result.fragments)
    assert_wire(result, groups, 1400)


def test_long_sentence_can_deliver_late_query_evidence():
    text = "background " * 500 + "cobalt sensor measures temperature near the outlet " + "appendix " * 50
    groups = (group(text),)
    result = build(groups, "cobalt sensor temperature", max_bytes=900)
    assert any(fragment.start > 4000 and "cobalt sensor" in fragment.text for fragment in result.fragments)
    assert_wire(result, groups, 900)


def test_citations_do_not_mix_scopes_or_artifact_revisions():
    text = "Cobalt sensor calibration was verified."
    groups = (group(text), group(text, artifact="other"), group(text, scope="other-scope"))
    result = build(groups, "Cobalt sensor calibration", max_bytes=4000)
    assert len(result.fragments) == 3
    assert_wire(result, groups, 4000)


def test_duplicate_exact_candidates_are_not_repeated():
    item = group("Cobalt sensor calibration was verified.")
    result = build((item, item), "Cobalt sensor calibration")
    assert len(result.fragments) == 1


def test_unrelated_query_does_not_emit_arbitrary_first_sentence():
    assert build((group("Cobalt exposure affects neurons."),), "zzzzdistinctterm").context.status == "empty"


@pytest.mark.parametrize("budget", [512, 800, 1000, 1400, 1800])
def test_unicode_escaping_and_complete_output_budget(budget):
    groups = (group('海洋观测 station: "quoted" \\ path. 海洋观测 station records 🐟 temperature. ' * 20),)
    result = build(groups, "海洋观测 station temperature", max_bytes=budget)
    assert_wire(result, groups, budget)
    if budget >= 1000:
        assert result.fragments


def test_query_switches_the_selected_evidence():
    groups = (group("Cobalt exposure reduces viability. Amber exposure increases glucose."),)
    cobalt = build(groups, "cobalt viability", max_bytes=750)
    amber = build(groups, "amber glucose", max_bytes=750)
    assert "viability" in (cobalt.context.content or "")
    assert "glucose" in (amber.context.content or "")
    assert cobalt.fragments != amber.fragments


def test_mismatched_candidate_reference_is_rejected():
    item = group("Cobalt exposure affects neurons.")
    wrong = PreparedMemoryCandidates(
        scope_id=item.scope_id, memory_ref=ArtifactRef(family="memory", artifact_id="other", revision=1), hits=item.hits
    )
    with pytest.raises(PreparedContextInvariantError):
        build((wrong,), "Cobalt exposure")


@pytest.mark.asyncio
async def test_multiple_literal_fragments_read_back_through_real_memory():
    text = "Cobalt reduces viability. " + "Administrative notes. " * 80 + "Cobalt increases inflammation."
    async with open_builtin_runtime(BuiltinConfig()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(
            ScopeDraft(title="Evidence", summary="Literal spans", idempotency_key="spans")
        )
        memory = runtime.memory.for_scope(scope.scope_id)
        await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=text),)))
        page = await memory.search(SearchMemoryRequest(query="Cobalt viability inflammation", mode="fts", limit=16))
        groups = (PreparedMemoryCandidates(scope_id=scope.scope_id, memory_ref=page.memory_ref, hits=page.hits),)
        result = build(groups, "Cobalt viability inflammation", max_bytes=1800)
        assert len(result.fragments) == 2
        assert_wire(result, groups, 1800)
        from powercontext.artifacts import MemoryCitation

        for fragment in result.fragments:
            citation = MemoryCitation(
                memory_ref=fragment.address.memory.artifact,
                entry_id=fragment.address.entry_id,
                entry_version_id=fragment.address.entry_version_id,
            )
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            assert fragment.text == entry.text[fragment.start : fragment.end]
