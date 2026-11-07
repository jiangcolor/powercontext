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
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

from pydantic import BaseModel
from pypdf import PdfReader

from powercontext.artifacts import MemoryCitation
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import ScopedMemoryApplication

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


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of one PDF revision, in order, without partial results."""

    if not isinstance(value.document_id, str) or not value.document_id.strip():
        raise ValueError("document_id must be a non-blank string")  # noqa: TRY003
    if not value.content:
        raise ValueError("pdf content must not be empty")  # noqa: TRY003

    if not value.content.rstrip(b"\x00\t\n\x0c\r ").endswith(b"%%EOF"):
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


# Query vocabulary is general accounting terminology, separate from report contents.
_TOPICS = (
    (
        "geography geographic geographies region regions countries country segments markets",
        r"business overview|(?:our |reportable |operating )?(?:segments|divisions)\b|geographic|item 1 business",
    ),
    (
        "legal litigation lawsuit lawsuits proceedings contingencies battles disputes",
        r"legal proceedings|litigation|commitments and contingencies",
    ),
    ("restructuring reorganization realignment severance", r"restructuring|reorganization|realignment"),
    (
        "income earnings profit loss revenue revenues sales turnover margin ebitda eps",
        r"(?:consolidated )?(?:income statements?|statements? of (?:income|operations|earnings|profit and loss))",
    ),
    (
        "cash flow flows cashflow capex depreciation amortization ebitda",
        r"(?:consolidated )?(?:cash flows? statements?|statements? of cash flows?)",
    ),
    (
        "assets liabilities equity inventory inventories receivables payables balance debt borrowings working capital",
        r"(?:consolidated )?(?:balance sheets?|statements? of financial position)",
    ),
)
_SYNONYMS = (
    "revenue revenues sales turnover",
    "debt borrowings borrowing obligations indebtedness",
    "dividends dividend distributions",
    "capex capital expenditures expenditure additions purchases property equipment",
    "income earnings profit profits",
    "inventory inventories",
    "repurchases repurchase buybacks buyback",
    "ebitda depreciation amortization",
    "legal litigation lawsuit lawsuits proceedings contingencies battles disputes",
    "geography geographic geographies region regions countries country segments markets",
    "restructuring reorganization realignment severance",
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


_WORD = re.compile(r"[^\W_]+")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_FILING_WORDS = frozenset([
    "annual",
    "report",
    "form",
    "10",
    "k",
    "q",
    "10k",
    "10q",
    "8k",
    "pdf",
    "inc",
    "ltd",
    "limited",
    "corporation",
    "corp",
    "company",
    "co",
])


def _terms(text: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(re.sub(r"\bfy\s*(?=\d{4}\b)", "", text.casefold())))


@dataclass(frozen=True, slots=True)
class _SearchPage:
    citation: MemoryCitation
    document_id: str
    text: str


def _report_identity(document_id: str) -> tuple[tuple[str, ...], frozenset[str]]:
    words = _terms(document_id)
    return (
        tuple(word for word in words if not word.isdigit() and word not in _FILING_WORDS),
        frozenset(word for word in words if _YEAR.fullmatch(word)),
    )


def _report_signals(document_ids: set[str], query: tuple[str, ...]) -> tuple[dict[str, int], set[str]]:
    # Derive filing hints solely from the documents actually present in scope.
    # Opaque IDs simply leave all companies equally weighted.
    words = set(query)
    years = {word for word in query if _YEAR.fullmatch(word)}
    identities = {doc: _report_identity(doc) for doc in document_ids}
    compact_phrases = {left + right for left, right in pairwise(query)}
    matched_names = {
        doc: names
        for doc, (names, _) in identities.items()
        if names and (set(names) <= words or "".join(names) in words or "".join(names) in compact_phrases)
    }
    bonuses = {}
    for doc, (_, filing_years) in identities.items():
        matching_year = bool(years & filing_years)
        if doc in matched_names:
            bonuses[doc] = 12 + 10 * matching_year
        elif not matched_names:
            bonuses[doc] = 2 * matching_year
    return bonuses, {word for names in matched_names.values() for word in (*names, "".join(names))}


def _heading_bonus(text: str, patterns: tuple[str, ...]) -> int:
    heading = " ".join(_terms(text)[:35])
    heading = re.sub(r"^table of contents ", "", heading)
    if heading.startswith(("table of contents", "index", "report of independent")):
        return 0
    lines = tuple(re.sub(r"^condensed ", "", " ".join(_terms(line))) for line in text.splitlines()[:5])
    return 7 * sum(any(re.match(pattern, line) for line in (heading, *lines)) for pattern in patterns)


def _rank_pages(
    pages: list[_SearchPage], question: str, search_order: dict[str, int]
) -> list[tuple[float, int, int, MemoryCitation]]:
    query = _terms(question)
    document_scores, entity_words = _report_signals({page.document_id for page in pages}, query)
    terms = tuple(
        dict.fromkeys(
            word
            for word in query
            if word not in _STOP_WORDS and word not in entity_words and not word.isdigit() and len(word) > 1
        )
    )
    topic_terms = set(terms)
    headings = tuple(pattern for words, pattern in _TOPICS if topic_terms.intersection(words.split()))
    expanded = dict.fromkeys(terms, 1.0)
    for group in _SYNONYMS:
        words = group.split()
        if topic_terms.intersection(words):
            for word in words:
                expanded.setdefault(word, 0.55)
    if not expanded:
        return []

    tokenized = [(page, _terms(page.text)) for page in pages]
    counts = [Counter(tokens) for _, tokens in tokenized]
    frequency = Counter(term for count in counts for term in expanded.keys() & count.keys())
    avg_length = sum(len(tokens) for _, tokens in tokenized) / len(pages) or 1
    idfs = {term: math.log1p((len(pages) - frequency[term] + 0.5) / (frequency[term] + 0.5)) for term in expanded}
    phrases = set(pairwise(query))
    phrases = {(left, right) for left, right in phrases if left in topic_terms and right in topic_terms}

    ranked = []
    for order, ((page, tokens), count) in enumerate(zip(tokenized, counts, strict=True)):
        norm = 1.2 * (0.25 + 0.75 * len(tokens) / avg_length)
        score = sum(
            weight * idfs[term] * count[term] * 2.2 / (count[term] + norm)
            for term, weight in expanded.items()
            if count[term]
        )
        score += _heading_bonus(page.text, headings)
        if score <= 0:
            continue
        score += 1.4 * len(phrases.intersection(pairwise(tokens)))
        score += document_scores.get(page.document_id, 0)
        rank = search_order.get(page.citation.entry_version_id, len(search_order))
        ranked.append((-score, rank, order, page.citation))
    return ranked


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = DEFAULT_PDF_SEARCH_LIMIT
) -> tuple[MemoryCitation, ...]:
    """Search the current scoped Memory and rank persisted evidence pages offline.

    Memory's FTS result order breaks lexical ranking ties. Read the full active
    scope through the public Memory API for reranking so a capped FTS result
    cannot drop a relevant report or a page matching only part of the question.
    """

    from powercontext.builtin.runtime import SearchMemoryRequest

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-blank string")  # noqa: TRY003
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003

    entries = await memory.list()
    pages = []
    seen = set()
    for record in entries.entries:
        sources = record.entry.sources
        if len(sources) != 1:
            continue
        source_id = sources[0].source_id
        if not source_id.startswith("pdf-page:") or source_id in seen:
            continue
        parts = source_id.removeprefix("pdf-page:").rsplit(":", 2)
        if len(parts) != 3:
            continue
        key, _, _ = parts
        document_id = record.entry.text.partition("\n")[0] if key.startswith("sha256:") else unquote(key)
        body = record.entry.text.removeprefix(document_id.strip() + "\n")
        if body == record.entry.text:
            _, _, body = record.entry.text.partition("\n")
        if not body.strip():
            continue
        seen.add(source_id)
        pages.append(_SearchPage(record.citation, document_id, body))
    if not pages:
        return ()

    result = await memory.search(SearchMemoryRequest(query=question, mode="fts", limit=min(limit, 100)))
    search_order = {hit.entry_version_id: rank for rank, hit in enumerate(result.hits)}
    ranked = _rank_pages(pages, question, search_order)
    return tuple(citation for _, _, _, citation in sorted(ranked, key=lambda item: item[:3])[:limit])


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
