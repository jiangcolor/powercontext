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

"""Capture every physical page of a PDF as addressable page-level evidence."""

from __future__ import annotations

import hashlib
import io
import math
import re
from collections import Counter
from collections.abc import Iterable
from itertools import pairwise
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel
from pypdf import PdfReader

from powercontext.artifacts import MemoryCitation
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PDF_PAGE_SOURCE_NAME = "pdf-page"
PDF_PAGE_SOURCE_VERSION = "1"
DEFAULT_PDF_SEARCH_LIMIT = 10


class PDFDocumentInput(BaseModel):
    """One complete original PDF file."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical page and the identity of the revision it belongs to."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """A captured page Source addressed by document, revision, and physical page."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Build a revision-specific identity, hashing long document names without truncation."""

    source_id = f"{PDF_PAGE_SOURCE_NAME}:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        document_key = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
        source_id = f"{PDF_PAGE_SOURCE_NAME}:sha256:{document_key}:{document_sha256}:{page_number}"
    return source_id


def parse_pdf_document(value: PDFDocumentInput, /) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of one PDF revision, in order, without partial results."""

    if not isinstance(value.document_id, str) or not value.document_id.strip():
        raise ValueError("document_id must be a non-blank string")  # noqa: TRY003
    if not value.content:
        raise ValueError("pdf content must not be empty")  # noqa: TRY003

    if b"%%EOF" not in value.content:
        raise ValueError("pdf is missing its end-of-file marker")  # noqa: TRY003

    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("pdf requires a user password")  # noqa: TRY003, TRY301
        total = len(reader.pages)
        pages: list[PDFPageInput] = []
        for index in range(total):
            text = reader.pages[index].extract_text() or ""
            pages.append(
                PDFPageInput(
                    document_id=value.document_id,
                    document_sha256=digest,
                    page_number=index + 1,
                    text=text,
                )
            )
    except ValueError:
        raise
    except Exception as error:  # any parser failure means the document is unusable
        raise ValueError("pdf document cannot be parsed completely") from error  # noqa: TRY003

    if not pages:
        raise ValueError("pdf document must contain at least one page")  # noqa: TRY003
    return tuple(pages)


# Offline vocabulary connects common financial question wording to report terminology.
# These are domain synonyms, independent of any document, question ID, or labelled page.
_CONCEPTS = (
    ("geography geographic geographies region regions countries country operates operations markets",),
    ("legal litigation lawsuit lawsuits proceedings contingencies battles disputes",),
    ("restructuring reorganization realignment severance impairment",),
    ("ebitda operating income depreciation amortization",),
    ("capex capital expenditures expenditure additions property equipment",),
    ("income earnings profit loss operations",),
    ("cash flows cashflow activities",),
    ("revenue revenues sales turnover",),
    ("debt borrowings borrowing obligations indebtedness",),
    ("dividends dividend distributions",),
)
_STOP_WORDS = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "for",
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "from",
    "with",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "what",
    "which",
    "who",
    "how",
    "why",
    "when",
    "where",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "i",
    "we",
    "you",
    "it",
    "its",
    "our",
    "your",
    "this",
    "that",
    "these",
    "those",
    "please",
    "has",
    "have",
    "had",
    "any",
    "primarily",
    "reported",
    "materially",
    "important",
    "ongoing",
    "directly",
    "outlined",
    "explicitly",
    "then",
    "state",
    "quantity",
    "define",
    "answer",
    "usd",
    "millions",
    "respond",
    "question",
    "assuming",
    "perspective",
    "investment",
    "analyst",
    "only",
    "use",
    "details",
    "shown",
    "within",
    "give",
    "response",
    "relying",
    "calculate",
    "using",
    "unadjusted",
    "adjusted",
    "fiscal",
    "fy",
    "year",
    "years",
])


def _terms(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[^\W_]+", re.sub(r"\bfy(?=\d{4}\b)", "", text.casefold())))


def _financial_queries(question: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    terms = tuple(dict.fromkeys(term for term in _terms(question) if term not in _STOP_WORDS))
    groups = tuple(group[0] for group in _CONCEPTS if set(group[0].split()).intersection(terms))
    # Short queries avoid the Memory admission floor rejecting pages that support only
    # one part of a multi-statement question. Every candidate still comes from Memory.
    queries = tuple(dict.fromkeys((" ".join(terms), *groups, *terms[:32])))
    return terms, tuple(query for query in queries if query)


def _rank_pages(
    candidates: Iterable[tuple[MemoryCitation, str]], terms: tuple[str, ...]
) -> list[tuple[float, int, MemoryCitation]]:
    documents = [(citation, text, Counter(_terms(text))) for citation, text in candidates]
    frequency = Counter(term for _, _, counts in documents for term in counts)
    average_length = sum(sum(counts.values()) for _, _, counts in documents) / len(documents) or 1
    expanded = dict.fromkeys(terms, 1.0)
    for group in _CONCEPTS:
        words = group[0].split()
        if set(words).intersection(terms):
            for word in words:
                expanded.setdefault(word, 0.35)

    ranked = []
    for order, (citation, text, counts) in enumerate(documents):
        length = sum(counts.values())
        score = 0.0
        for term, weight in expanded.items():
            count = counts[term]
            if count:
                idf = math.log(1 + (len(documents) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                score += weight * idf * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / average_length))
        # Exact adjacent question terms help distinguish a financial statement from
        # incidental mentions scattered through a long exhibit.
        body = " ".join(_terms(text))
        score += sum(0.75 for left, right in pairwise(terms) if f"{left} {right}" in body)
        ranked.append((-score, order, citation))

    return ranked


async def search_pdf_pages(
    memory: Any, question: str, limit: int = DEFAULT_PDF_SEARCH_LIMIT
) -> tuple[MemoryCitation, ...]:
    """Search persisted pages, rerank lexical evidence, and return exact page citations.

    Candidate retrieval uses only the supplied scoped Memory's public search API.
    BM25 and financial terminology expansion are deterministic and entirely offline.
    Work is bounded by 43 searches of at most 160 candidates each; no corpus or
    query state is cached across scopes or runtime restarts.
    """

    from powercontext.builtin.runtime import GetMemoryEntryRequest, SearchMemoryRequest

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-blank string")  # noqa: TRY003
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003

    terms, queries = _financial_queries(question)
    if not queries:
        return ()
    candidates = {}
    for query in queries:
        result = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=160))
        for hit in result.hits:
            citation = MemoryCitation(
                memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
            )
            key = citation.model_dump_json()
            candidates.setdefault(key, (citation, hit.text))
    if not candidates:
        return ()

    ranked = _rank_pages(candidates.values(), terms)

    citations = []
    seen = set()
    for _, _, citation in sorted(ranked, key=lambda item: item[:2]):
        record = await memory.get(GetMemoryEntryRequest(citation=citation))
        # Page identity is the persisted Source reference, rather than the Memory
        # entry ID: two entries can refer to the same captured physical page.
        page_sources = tuple(
            sorted(source.source_id for source in record.entry.sources if source.source_id.startswith("pdf-page:"))
        )
        if not page_sources or page_sources in seen:
            continue
        seen.add(page_sources)
        citations.append(citation)
        if len(citations) == limit:
            break
    return tuple(citations)


class _PDFPageAdapter:
    """Resolve and read page values without touching a catalog."""

    input_class: type[PDFPageInput] = PDFPageInput
    source_class: type[PDFPageSource] = PDFPageSource
    name = PDF_PAGE_SOURCE_NAME

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        source_id = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class _PDFPageTextEvidence:
    """Project one page into the standard text-evidence shape."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class: type[PDFPageSource] = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput](
    adapter=_PDFPageAdapter(),
    version=PDF_PAGE_SOURCE_VERSION,
    projections=(_PDFPageTextEvidence(),),
)


__all__ = [
    "DEFAULT_PDF_SEARCH_LIMIT",
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDF_PAGE_SOURCE_VERSION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
