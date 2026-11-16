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
import zlib
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

from pydantic import BaseModel
from pypdf import PdfReader, get_configuration
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, EncodedStreamObject, NameObject, NullObject

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
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("pdf requires a user password")  # noqa: TRY003, TRY301
        total = len(reader.pages)
        pages: list[PDFPageInput] = []
        for index in range(total):
            page = reader.pages[index]
            # Text extraction can return early for pages without font resources,
            # hiding broken references or malformed content as an empty page.
            _validate_page_content(
                page.get("/Contents"), page.get("/Resources", DictionaryObject()).get_object(), reader, set()
            )
            text = _extract_page_text(page)
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
    return _restore_missing_glyphs(pages)


_LIGATURES = str.maketrans(dict(zip("ﬀﬁﬂﬃﬄﬅﬆ", ("ff", "fi", "fl", "ffi", "ffl", "st", "st"), strict=True)))
_BROKEN_LINE_WORD = re.compile(r"\b[A-Za-z]{1,3}\n[A-Za-z]{2,}\b|\b[A-Za-z]{2,}\n[A-Za-z]{1,3}\b")
_MISSING_GLYPH_WORD = re.compile(r"[A-Za-z]+(?:\x00[A-Za-z]*)+")


def _validate_content_encoding(value) -> None:
    """Reject compressed content that pypdf's recovery decoder would truncate."""
    if value is None:
        return
    stream = value.get_object()
    if isinstance(stream, ArrayObject):
        for item in stream:
            _validate_content_encoding(item)
        return
    if not isinstance(stream, EncodedStreamObject):
        return
    filters = stream.get("/Filter", ArrayObject()).get_object()
    filters = (filters,) if isinstance(filters, str) else filters
    parameters = stream.get("/DecodeParms", DictionaryObject()).get_object()
    # pypdf exposes decoded bytes through get_data(); its pinned StreamObject
    # representation retains the encoded bytes in _data, needed to check EOF.
    data = stream._data
    for index, filter_name in enumerate(filters):
        if filter_name in ("/FlateDecode", "/Fl"):
            decoder = zlib.decompressobj()
            decoder.decompress(data, get_configuration().zlib_maximum_output_length)
            if not decoder.eof:
                raise ValueError("pdf page contains an incomplete compressed stream")  # noqa: TRY003
        step = EncodedStreamObject()
        step._data = data
        step[NameObject("/Filter")] = filter_name
        if isinstance(parameters, ArrayObject):
            step[NameObject("/DecodeParms")] = parameters[index]
        elif parameters:
            step[NameObject("/DecodeParms")] = parameters
        data = step.get_data()


def _validate_page_content(value, resources, reader: PdfReader, ancestors: set[int]) -> None:
    if value is None or isinstance(value.get_object(), NullObject):
        return
    _validate_content_encoding(value)
    content = ContentStream(value, reader)
    for operands, operator in content.operations:
        if operator != b"Do":
            continue
        form = resources["/XObject"][operands[0]]
        if form.get("/Subtype") != "/Form":
            continue
        if id(form) in ancestors:
            raise ValueError("pdf page contains a recursive form")  # noqa: TRY003
        # The text extractor catches errors inside Form XObjects. Validate their
        # streams first so a damaged form cannot silently lose part of a page.
        _validate_page_content(form, form.get("/Resources", resources).get_object(), reader, ancestors | {id(form)})


def _extract_page_text(page) -> str:
    text = page.extract_text() or ""
    if _BROKEN_LINE_WORD.search(text):
        layout = page.extract_text(extraction_mode="layout", layout_mode_strip_rotated=False)
        # A font/size change can invent a line break inside a word. Use geometry
        # only when it retains every non-whitespace character from the page.
        if Counter("".join(text.split())) == Counter("".join(layout.split())) and len(
            re.findall(r"[a-z]+|\d+", layout.lower())
        ) < len(re.findall(r"[a-z]+|\d+", text.lower())):
            text = "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in layout.splitlines()).strip()
    return _repair_table_labels(text.translate(_LIGATURES))


def _restore_missing_glyphs(pages: list[PDFPageInput]) -> tuple[PDFPageInput, ...]:
    # Some embedded fonts explicitly map a ligature to U+0000. Only restore a
    # word if the PDF itself supplies exactly one intact matching spelling.
    vocabulary: dict[int, set[str]] = {}
    for page in pages:
        for word in re.findall(r"(?<![A-Za-z\x00])[A-Za-z]{4,80}(?![A-Za-z\x00])", page.text):
            vocabulary.setdefault(len(word), set()).add(word.lower())

    def restore(match: re.Match[str]) -> str:
        broken = match[0]
        pattern = re.compile(broken.lower().replace("\x00", "[a-z]{1,3}"))
        minimum = len(broken)
        maximum = minimum + 2 * broken.count("\x00")
        candidates = {
            word for size in range(minimum, maximum + 1) for word in vocabulary.get(size, ()) if pattern.fullmatch(word)
        }
        if len(candidates) != 1:
            return broken
        word = candidates.pop()
        if broken.isupper():
            return word.upper()
        if broken[0].isupper():
            return word.capitalize()
        return word

    return tuple(page.model_copy(update={"text": _MISSING_GLYPH_WORD.sub(restore, page.text)}) for page in pages)


_LABEL_WORD = re.compile(r"[^\W\d_]+")
_NUMERIC_ROW_LABEL = re.compile(r"^([^\d\n]+?)(?=\s+\$?\s*\(?\d[\d,.]*\)?\s{2,}\$?\s*\(?\d)", re.M)
_FRAGMENT_RUN = re.compile(r"[^\W\d_]+(?: [^\W\d_]+){1,8}")


def _repair_table_labels(text: str) -> str:
    """Join split glyph runs only in table labels with an intact spelling on the page.

    Keep original characters, case, and numeric columns. The same-page spelling
    supplies evidence for the join; prose is outside the numeric row pattern.
    """
    words = {w.casefold() for w in _LABEL_WORD.findall(text) if len(w) >= 4}

    def restore(match: re.Match[str]) -> str:
        parts = match[0].split(" ")
        corrected = []
        i = 0
        while i < len(parts):
            for j in range(len(parts), i + 1, -1):
                fragment = parts[i:j]
                joined = "".join(fragment)
                if joined.casefold() in words and (len(fragment) >= 3 or any(len(p) <= 3 for p in fragment)):
                    corrected.append(joined)
                    i = j
                    break
            else:
                corrected.append(parts[i])
                i += 1
        return " ".join(corrected)

    return _NUMERIC_ROW_LABEL.sub(lambda m: _FRAGMENT_RUN.sub(restore, m[0]), text)


# Query vocabulary is general accounting terminology, separate from report contents.
_TOPICS = (
    (
        "geography geographic geographies region regions countries country segment segments markets product products service services",
        r"business overview|(?:our |reportable |operating )?(?:segments|divisions)\b|geographic|item 1 business|.*\bby business segment\b|performance by business|(?:summary of )?business segment",
    ),
    (
        "legal litigation lawsuit lawsuits proceedings contingencies battles disputes",
        r"legal proceedings|litigation|commitments and contingencies",
    ),
    ("restructuring reorganization realignment severance", r"restructuring|reorganization|realignment"),
    (
        "income earnings profit loss revenue revenues sales turnover margin ebitda eps intensive growth grow",
        r"(?:consolidated )?(?:income statements?|statements? of (?:income|operations|earnings|profit and loss))",
    ),
    (
        "cash flow flows cashflow capex depreciation amortization ebitda intensive",
        r"(?:consolidated )?(?:cash flows? statements?|statements? of cash flows?)",
    ),
    (
        "assets liabilities liability equity inventory inventories receivables payables balance debt borrowings working capital liquidity quick ratio ppne ppe property equipment",
        r"(?:consolidated )?(?:balance sheets?|statements? of financial position)",
    ),
    (
        "tax taxes taxation",
        r"(?:note \d+ )?(?:income taxes|taxation)|(?:consolidated )?statements? of (?:income|operations|earnings)",
    ),
)
_SYNONYMS = (
    "revenue revenues sales turnover",
    "debt borrowings borrowing obligations indebtedness",
    "dividends dividend distributions",
    "capex capital expenditures expenditure additions purchases property plant equipment ppne ppe",
    "income earnings profit profits",
    "inventory inventories",
    "repurchases repurchase buybacks buyback",
    "ebitda depreciation amortization",
    "legal litigation lawsuit lawsuits proceedings contingencies battles disputes",
    "geography geographic geographies region regions countries country segments markets",
    "restructuring reorganization realignment severance",
    "liquidity quick current assets liabilities cash receivables inventory",
    "capital intensive property equipment expenditures assets revenue",
    "tax taxes taxation effective rate",
    "products product services service business segment segments",
    "customers customer clients client consumers consumer",
    "cyclicality cyclical cycles economic demand downturn",
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
    "company",
    "financial",
    "analyst",
    "based",
    "data",
    "much",
    "useful",
    "relevant",
    "metric",
    "metrics",
    "measure",
    "something",
    "like",
    "ask",
    "about",
    "explain",
    "whether",
    "profile",
    "reasonably",
    "healthy",
    "primary",
    "major",
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
    text = re.sub(r"\bfy\s*(\d{2})\b", lambda m: ("20" if int(m[1]) < 70 else "19") + m[1], text.casefold())
    return tuple(_WORD.findall(re.sub(r"\bfy\s*(?=\d{4}\b)", "", text)))


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
        if names
        and (
            set(names) <= words
            or "".join(names) in words
            or "".join(names) in compact_phrases
            or (len(names) > 1 and {"".join(name[0] for name in names), "n".join(name[0] for name in names)} & words)
        )
    }
    if not matched_names:
        # Match contractions using only names present in this scope. Require a
        # unique document name, a shared prefix, and ordered letters; do not
        # maintain a company-specific alias table.
        for word in words - _STOP_WORDS:
            matches = {}
            for doc, (names, _) in identities.items():
                name = "".join(names)
                letters = iter(name)
                if 4 <= len(word) <= len(name) // 2 and name.startswith(word[:2]) and all(c in letters for c in word):
                    matches[doc] = names
            if len(set(matches.values())) == 1:
                matched_names.update(matches)
    bonuses = {}
    for doc, (_, filing_years) in identities.items():
        matching_year = bool(years & filing_years)
        if doc in matched_names:
            bonuses[doc] = 12 + 10 * matching_year
        elif not matched_names:
            bonuses[doc] = 2 * matching_year
    entity_words = {word for names in matched_names.values() for word in (*names, "".join(names))}
    entity_words.update(
        word for word in words if len(word) > 1 and any(word in "".join(names) for names in matched_names.values())
    )
    return bonuses, entity_words


def _heading_bonus(text: str, patterns: tuple[str, ...]) -> int:
    heading = " ".join(_terms(text)[:35])
    heading = re.sub(r"^table of contents ", "", heading)
    if heading.startswith("report of independent"):
        return 0
    lines = tuple(re.sub(r"^condensed ", "", " ".join(_terms(line))) for line in text.splitlines() if line.strip())[:8]
    return 14 * sum(any(re.match(pattern, line) for line in (heading, *lines)) for pattern in patterns)


def _topic_terms(terms: tuple[str, ...]) -> set[str]:
    variants = set(terms)
    for term in terms:
        if term.endswith("ies") and len(term) > 4:
            variants.add(term[:-3] + "y")
        elif term.endswith("s") and not term.endswith(("ss", "us", "is")) and len(term) > 3:
            variants.add(term[:-1])
    return variants


def _rank_pages(
    pages: list[_SearchPage], question: str, search_order: dict[str, int]
) -> list[tuple[int, float, int, int, MemoryCitation]]:
    query = _terms(question)
    document_scores, entity_words = _report_signals({page.document_id for page in pages}, query)
    terms = tuple(
        dict.fromkeys(
            word
            for word in query
            if word not in _STOP_WORDS and word not in entity_words and not word.isdigit() and len(word) > 1
        )
    )
    topic_terms = _topic_terms(terms)
    headings = tuple(pattern for words, pattern in _TOPICS if topic_terms.intersection(words.split()))
    expanded = dict.fromkeys(terms, 1.0)
    for term in topic_terms:
        expanded.setdefault(term, 0.8)
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
    best_document_score = max(document_scores.values(), default=0)
    for order, ((page, tokens), count) in enumerate(zip(tokenized, counts, strict=True)):
        if best_document_score >= 12 and document_scores.get(page.document_id, 0) < best_document_score:
            continue
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
        rank = search_order.get(page.citation.entry_version_id, len(search_order))
        ranked.append((-document_scores.get(page.document_id, 0), -score, rank, order, page.citation))
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
    return tuple(citation for _, _, _, _, citation in sorted(ranked, key=lambda item: item[:4])[:limit])


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
