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


@pytest.mark.parametrize("suffix", [b"", b"6 0 obj\n<< /Type /Page >>"])
def test_missing_final_pdf_marker_is_not_accepted(suffix):
    original = blank_document()
    raw = original + suffix if suffix else original.replace(b"%%EOF", b"")
    with pytest.raises(ValueError):
        parse_pdf_document(value=PDFDocumentInput(document_id="broken", content=raw))


def test_parse_repairs_fragmented_numeric_table_label():
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=400)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        }),
    })
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 20 360 Td (Current liabilities:) Tj "
        b"0 -20 Td (Total  l i abi l i t i es  176,392    145,129) Tj "
        b"0 -20 Td (Narrative l i abi l i t i es remains verbatim.) Tj ET"
    )
    page[NameObject("/Contents")] = stream
    buffer = io.BytesIO()
    writer.write(buffer)
    result = parse_pdf_document(PDFDocumentInput(document_id="balance", content=buffer.getvalue()))
    assert "Total  liabilities  176,392    145,129" in result[0].text
    assert "Narrative l i abi l i t i es remains verbatim." in result[0].text


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
        "Consolidated statement of income. Net revenues 450. Operating income 130. Profit after tax 120.",
        "Business overview: sparkling beverages and snack products are sold to customers.",
        "Consolidated balance sheets. Short-term obligations 420. Long-term obligations 570.",
    )
    texts += tuple(
        f"Note {number}: EBITDA operating income depreciation amortization capital expenditures " * 4
        for number in range(25)
    )
    documents = {"Northstar_2024_10-K": texts}
    # Earlier filings repeat the target company's name and the comparative
    # reporting year even when their own primary statements are irrelevant.
    distractors = tuple(
        f"Consolidated Statements of Income\nNorthstar net income 7 {number} 2024. Net income net income. "
        "See current liabilities, total current liabilities and the comparative current liabilities."
        for number in range(25)
    )
    documents["Northstar_2023_10-K"] = distractors
    documents["Southbank_2024_10-K"] = distractors
    observations = []
    for document_id, pages in documents.items():
        for number, text in enumerate(pages, 1):
            source = await registry.resolve(
                PDFPageInput(
                    document_id=document_id,
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
        citations = await search_pdf_pages(memory, "Northstar FY2024 EBITDA less capex?", limit=3)
        retrieved = [(await memory.get(GetMemoryEntryRequest(citation=c))).entry.text for c in citations]
        assert any("Depreciation" in text for text in retrieved)
        assert any("Operating income" in text for text in retrieved)
        assert len({c.model_dump_json() for c in citations}) == len(citations)
        assert await search_pdf_pages(memory, "zzzzunknownword", limit=3) == ()

        citations = await search_pdf_pages(memory, "What were Northstar's current liabilities in FY2024?", limit=20)
        retrieved = [(await memory.get(GetMemoryEntryRequest(citation=c))).entry.text for c in citations]
        assert any(text.startswith("Northstar_2024_10-K\nConsolidated balance sheets.") for text in retrieved)
