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

"""Offline, query-directed selection of literal Memory sentence intervals."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.models import PrepareContextRequest, PreparedContext
from powercontext.builtin.runtime.prepared_context import (
    MemoryEntryAddress,
    PreparedContextBuild,
    PreparedEvidenceFragment,
    PreparedMemoryCandidates,
)
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

_STOP = frozenset([
    "a",
    "an",
    "the",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "from",
    "by",
    "with",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "and",
    "or",
    "but",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "their",
    "there",
    "we",
    "our",
    "they",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "can",
    "could",
    "may",
    "might",
    "will",
    "would",
    "should",
    "not",
    "no",
    "than",
    "then",
    "into",
    "which",
    "who",
    "what",
    "how",
    "when",
    "where",
    "through",
    "between",
    "during",
    "using",
    "used",
    "use",
])
_WORDS = re.compile(r"[a-z]+|\d+|[\u3400-\u9fff]", re.IGNORECASE)
_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+|\n+")  # noqa: RUF001


def _terms(text: str) -> Counter[str]:
    terms: Counter[str] = Counter()
    for word in _WORDS.findall(text.lower()):
        if word in _STOP:
            continue
        # A small conservative inflection normalizer, requiring no downloaded resources.
        if len(word) > 5 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "is", "us")):
            word = word[:-1]
        terms[word] += 1
    return terms


@dataclass(frozen=True)
class _Sentence:
    document: int
    start: int
    end: int
    terms: Counter[str]


def _intervals(text: str):
    start = 0
    for boundary in _BOUNDARY.finditer(text):
        end = boundary.start()
        if text[start:end].strip():
            yield from _bounded_intervals(text, start, end)
        start = boundary.end()
    if text[start:].strip():
        yield from _bounded_intervals(text, start, len(text))


def _bounded_intervals(text: str, start: int, end: int):
    """Retain useful evidence even in a long paragraph with no sentence punctuation."""
    while len(text[start:end].encode("utf-8")) > 600:
        stop = min(end, start + 200)
        boundary = text.rfind(" ", start + 80, stop)
        if boundary >= 0:
            stop = boundary
        yield start, stop
        start = stop
    if start < end and text[start:end].strip():
        yield start, end


def _render(fragments: Sequence[PreparedEvidenceFragment]) -> str:
    items = [
        {
            "citation": {
                "scope_id": fragment.address.memory.scope_id,
                "memory_ref": fragment.address.memory.artifact.model_dump(mode="json"),
                "entry_id": fragment.address.entry_id,
                "entry_version_id": fragment.address.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }
        for fragment in fragments
    ]
    body = json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
    return f"{TRUST_POLICY}\n\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n{body}\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1"


def _documents(groups: Sequence[PreparedMemoryCandidates]) -> list[tuple[MemoryEntryAddress, str]]:
    documents: list[tuple[MemoryEntryAddress, str]] = []
    seen = set()
    for group in groups:
        if group.hits and group.memory_ref is None:
            raise PreparedContextInvariantError("memory-ref-missing")
        for hit in group.hits:
            if hit.memory_ref != group.memory_ref:
                raise PreparedContextInvariantError("memory-ref-mismatch")
            address = MemoryEntryAddress(
                ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref), hit.entry_id, hit.entry_version_id
            )
            identity = (
                group.scope_id,
                hit.memory_ref.artifact_id,
                hit.memory_ref.revision,
                hit.entry_id,
                hit.entry_version_id,
            )
            if identity in seen or not hit.text.strip() or not hit.entry_id.strip() or not hit.entry_version_id.strip():
                continue
            seen.add(identity)
            documents.append((address, hit.text))
    return documents


def _rank_sentences(sentences, documents, query):
    frequency = Counter(term for sentence in sentences for term in sentence.terms)
    weights = {term: math.log1p(len(sentences) / (1 + frequency[term])) for term in query}
    average = sum(sum(sentence.terms.values()) for sentence in sentences) / len(sentences)

    def relevance(sentence: _Sentence) -> float:
        length = sum(sentence.terms.values())
        return sum(
            weights[term] * (count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / max(1, average))))
            for term in query
            if (count := sentence.terms[term])
        )

    scores = [relevance(sentence) for sentence in sentences]
    # A sentence's local context is useful even when it uses anaphora instead of query words.
    adjusted = [
        score
        + 0.18
        * max(
            (
                scores[j]
                for j in (i - 1, i + 1)
                if 0 <= j < len(sentences) and sentences[j].document == sentence.document
            ),
            default=0.0,
        )
        for i, (sentence, score) in enumerate(zip(sentences, scores, strict=True))
    ]
    ranked = sorted(range(len(sentences)), key=lambda i: (-adjusted[i], i))
    # Avoid allocating work proportional to repeated low-information boilerplate.
    candidates = []
    duplicate_text = set()
    for index in ranked:
        sentence = sentences[index]
        text = documents[sentence.document][1][sentence.start : sentence.end]
        key = (sentence.document, text)
        if adjusted[index] > 0 and key not in duplicate_text:
            duplicate_text.add(key)
            candidates.append(index)
        if len(candidates) >= 64:
            break

    return candidates, adjusted


def select_evidence(request: PrepareContextRequest, groups: Sequence[PreparedMemoryCandidates]) -> PreparedContextBuild:
    """Select sentences with lexical relevance and measure their complete serialized cost.

    Adjacent sentences share a citation by merging their original intervals, including
    the original whitespace. A bounded beam explores combinations so a long first hit
    cannot consume the budget before more useful later evidence is considered.
    """
    documents = _documents(groups)
    sentences = [
        _Sentence(index, start, end, _terms(text[start:end]))
        for index, (_, text) in enumerate(documents)
        for start, end in _intervals(text)
    ]
    query = _terms(request.query)
    if not sentences or not query:
        return PreparedContextBuild(PreparedContext(status="empty", content=None, content_bytes=0), ())
    candidates, adjusted = _rank_sentences(sentences, documents, query)

    def fragments(indices: tuple[int, ...]) -> tuple[PreparedEvidenceFragment, ...]:
        ranges: list[tuple[int, int, int]] = []
        for index in sorted(indices):
            sentence = sentences[index]
            if ranges and ranges[-1][0] == sentence.document:
                document, start, end = ranges[-1]
                if not documents[document][1][end : sentence.start].strip():
                    ranges[-1] = (document, start, sentence.end)
                    continue
            ranges.append((sentence.document, sentence.start, sentence.end))
        return tuple(
            PreparedEvidenceFragment(documents[document][0], start, end, documents[document][1][start:end])
            for document, start, end in ranges
        )

    # (utility, selected sentence indices, serialized byte count)
    beam: list[tuple[float, tuple[int, ...], int]] = [(0.0, (), 0)]
    for index in candidates:
        expanded = list(beam)
        for utility, selected, _ in beam:
            selection = tuple(sorted((*selected, index)))
            size = len(_render(fragments(selection)).encode("utf-8"))
            if size <= request.max_bytes:
                expanded.append((utility + adjusted[index], selection, size))
        # Keep both high utility and inexpensive alternatives for subsequent sentences.
        expanded.sort(key=lambda state: (-state[0], state[2], state[1]))
        beam = expanded[:24]
        cheapest = sorted(expanded, key=lambda state: (state[2], -state[0], state[1]))[:8]
        beam = list({state[1]: state for state in (*beam, *cheapest)}.values())
    best = max(beam, key=lambda state: (state[0], -state[2]))
    chosen = fragments(best[1])
    if not chosen:
        return PreparedContextBuild(PreparedContext(status="empty", content=None, content_bytes=0), ())
    content = _render(chosen)
    return PreparedContextBuild(
        context=PreparedContext(status="ready", content=content, content_bytes=len(content.encode("utf-8"))),
        origins=tuple(fragment.address for fragment in chosen),
        fragments=chosen,
    )
