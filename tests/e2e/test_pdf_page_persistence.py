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

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


class PagePipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(
                kind="source-evidence",
                text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                sources=(source,),
            )
            for source in request.sources
        )


@pytest.mark.asyncio
async def test_dense_page_revisions_preserve_exact_citations_and_scope(tmp_path):
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    dense_text = "Consolidated income statement\n" + "Revenue 120 operating expenses 80. " * 300
    observations = []
    for digest, token in (("a" * 64, "originalrevision"), ("b" * 64, "updatedrevision")):
        source = await registry.resolve(
            PDFPageInput(
                document_id="Dense_2025_10K",
                document_sha256=digest,
                page_number=1,
                text=dense_text + token,
            )
        )
        observations.append(project_source_for_transport(registry, source))
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pages.db'}"))
    async with open_builtin_runtime(config, candidate_pipeline=PagePipeline()) as runtime:
        scope = await runtime.scopes.create(
            ScopeDraft(title="Report", summary="PDF evidence", idempotency_key="report")
        )
        other = await runtime.scopes.create(ScopeDraft(title="Other", summary="Isolated", idempotency_key="other"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        request = SubmitSourceObservation(scope_id=scope.scope_id, observation=observations[0])
        await runtime.ingestion.submit(request)
        await runtime.ingestion.submit(request)
        memory = runtime.memory.for_scope(scope.scope_id)
        while (await memory.flush()).processed:
            pass
        entries = (await memory.list()).entries
        assert len(entries) == 1
        original = entries[0].citation
        assert len(entries[0].entry.text.encode()) > 8192

    async with open_builtin_runtime(config, candidate_pipeline=PagePipeline()) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        assert await search_pdf_pages(runtime.memory.for_scope(other.scope_id), "originalrevision") == ()
        assert await search_pdf_pages(memory, "originalrevision", limit=1) == (original,)
        await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observations[1]))
        while (await memory.flush()).processed:
            pass

    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        old = (await memory.get(GetMemoryEntryRequest(citation=original))).entry
        assert old.text == observations[0].projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"]
        assert old.sources[0].source_id == observations[0].name
        citations = await search_pdf_pages(memory, "updatedrevision", limit=1)
        assert len(citations) == 1
        new = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry
        assert new.text == observations[1].projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"]
        assert new.sources[0].source_id == observations[1].name
        assert new.sources != old.sources
        assert len((await memory.list()).entries) == 2
