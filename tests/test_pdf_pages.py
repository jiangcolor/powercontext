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

import hashlib
import io

import pytest
from pypdf import PdfWriter

from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def blank_document():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_long_unicode_document_names_preserve_revision_identity():
    raw = blank_document()
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    sources = []
    for document_id in ("财报" * 200, "财报" * 200 + "一", " spaced document "):
        page = parse_pdf_document(PDFDocumentInput(document_id=document_id, content=raw))[0]
        source = await registry.resolve(page)
        assert len(source.name) <= 256
        assert await registry.read(source) == page
        assert page.document_sha256 == hashlib.sha256(raw).hexdigest()
        sources.append(source.name)
    assert len(set(sources)) == 3


def test_missing_final_pdf_marker_is_not_accepted():
    raw = blank_document().replace(b"%%EOF", b"")
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="broken", content=raw))


@pytest.mark.asyncio
async def test_financial_paraphrase_search_survives_restart(tmp_path):
    from powercontext.builtin.artifacts.memory import MemoryEntryInput
    from powercontext.builtin.persistence.sqlite import SQLiteConfig
    from powercontext.builtin.runtime import (
        BuiltinConfig,
        GetMemoryEntryRequest,
        SubmitSourceObservation,
        open_builtin_runtime,
    )
    from powercontext.builtin.scope import ScopeDraft

    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    texts = (
        "Pending litigation and proceedings: the company faces a lawsuit in federal court.",
        "Consolidated statement of cash flows. Depreciation and amortization 91. Capital expenditures 120.",
        "Consolidated statement of income. Net revenues 450. Operating income 130.",
        "Business overview: sparkling beverages and snack products are sold to customers.",
    )
    observations = []
    for number, text in enumerate(texts, 1):
        source = await registry.resolve(
            PDFPageInput(
                document_id="synthetic",
                document_sha256="a" * 64,
                page_number=number,
                text=text,
            )
        )
        observation = project_source_for_transport(registry, source)
        observations.append(observation)
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pdf.db'}"))
    async with open_builtin_runtime(config) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="PDF", summary="Synthetic pages", idempotency_key="pdf"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for observation in observations:
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))

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

    async with open_builtin_runtime(config, candidate_pipeline=PagePipeline()) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        while (await memory.flush()).processed:
            pass
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        citations = await search_pdf_pages(memory, "Has the company faced legal battles?", limit=1)
        assert len(citations) == 1
        record = await memory.get(GetMemoryEntryRequest(citation=citations[0]))
        assert "litigation" in record.entry.text
        citations = await search_pdf_pages(memory, "EBITDA less capex?", limit=3)
        retrieved = [(await memory.get(GetMemoryEntryRequest(citation=c))).entry.text for c in citations]
        assert any("Depreciation" in text for text in retrieved)
        assert any("Operating income" in text for text in retrieved)
        assert len({c.model_dump_json() for c in citations}) == len(citations)
        assert await search_pdf_pages(memory, "zzzzunknownword", limit=3) == ()
