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

"""Offline lexical passage scoring over caller-supplied literal Memory text."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations, pairwise

_SENTENCE_BREAK = re.compile(r"(?<=[.!?。！？])\s+|\n+")  # noqa: RUF001
_WORD = re.compile(r"[^\W_]+")
_STOP = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "for",
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
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "they",
    "their",
    "we",
    "our",
    "you",
    "your",
    "which",
    "who",
    "what",
    "how",
    "when",
    "where",
    "than",
    "then",
    "also",
    "can",
    "could",
    "may",
    "might",
    "would",
    "should",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
])


@dataclass(frozen=True)
class EvidencePassage:
    spans: tuple[tuple[int, int], ...]
    score: float


def _stem(word: str) -> str:
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_stem(word) for word in _WORD.findall(text.casefold()) if word not in _STOP)


def sentence_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Find sentence boundaries without normalizing original character positions."""
    spans = []
    start = 0
    for match in _SENTENCE_BREAK.finditer(text):
        if text[start : match.start()].strip():
            spans.append((start, match.start()))
        start = match.end()
    if text[start:].strip():
        spans.append((start, len(text)))
    return tuple(spans)


def _merge_spans(text: str, spans: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and (start <= merged[-1][1] or not text[merged[-1][1] : start].strip()):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def passage_options(texts: Sequence[str], query: str) -> tuple[tuple[EvidencePassage, ...], ...]:
    """Rank bounded sentence/window options, using only query and candidate text.

    IDF is measured over the supplied sentences. Adjacent sentences share one
    citation when merged; disjoint evidence retains distinct source intervals.
    No labels, document identifiers, model calls, or persisted caches are used.
    """
    terms = frozenset(_tokens(query))
    if not terms:
        return tuple(() for _ in texts)
    all_spans = tuple(sentence_spans(text) for text in texts)
    counts = [
        Counter(_tokens(text[start:end])) for text, spans in zip(texts, all_spans, strict=True) for start, end in spans
    ]
    if not counts:
        return tuple(() for _ in texts)
    frequency = Counter(term for count in counts for term in count)
    average_length = sum(sum(count.values()) for count in counts) / len(counts) or 1.0
    weights = {term: math.log(1 + (len(counts) - frequency[term] + 0.5) / (frequency[term] + 0.5)) for term in terms}
    query_pairs = tuple(pairwise(_tokens(query)))

    def score(text: str) -> float:
        counts = Counter(_tokens(text))
        length = sum(counts.values())
        value = sum(
            weights[term] * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / average_length))
            for term in terms
            if (count := counts[term])
        )
        tokens = set(pairwise(_tokens(text)))
        return value + 0.5 * sum(pair in tokens for pair in query_pairs)

    results = []
    for text, spans in zip(texts, all_spans, strict=True):
        options = _document_passages(text, spans, terms, score)
        distinct = {}
        for ranges, value in options.items():
            key = tuple(text[start:end] for start, end in ranges)
            distinct.setdefault(key, (ranges, value))
        options = dict(distinct.values())
        ranked = sorted(options.items(), key=lambda item: (-item[1], item[0]))
        # Retain both high-value and economical options; long passages must not
        # crowd all short, fitting evidence out of the bounded option pool.
        economical = sorted(
            options.items(), key=lambda item: -item[1] / (180 + sum(len(text[a:b].encode("utf-8")) for a, b in item[0]))
        )
        shortest = sorted(
            options.items(), key=lambda item: sum(len(text[a:b].encode("utf-8")) + 180 for a, b in item[0])
        )
        choices = dict(ranked[:16] + economical[:8] + shortest[:8])
        results.append(tuple(EvidencePassage(spans=spans, score=value) for spans, value in choices.items()))
    return tuple(results)


def _document_passages(
    text: str, spans: Sequence[tuple[int, int]], terms: frozenset[str], score: Callable[[str], float]
) -> dict[tuple[tuple[int, int], ...], float]:
    scored = [(start, end, score(text[start:end])) for start, end in spans]
    options: dict[tuple[tuple[int, int], ...], float] = {}
    for index, (start, end, value) in ((index, item) for index, item in enumerate(scored) if item[2] > 0):
        options[((start, end),)] = value
        # Evidence often spans a result and its explanation. Include nearby
        # sentences, preserving intervening text and its original offsets.
        for width in range(2, min(4, len(scored) - index) + 1):
            window = scored[index : index + width]
            ranges = ((start, window[-1][1]),)
            options[ranges] = sum(item[2] for item in window) / (1 + 0.12 * (width - 1))
        for left, right in _query_windows(text, start, end, terms):
            options[((left, right),)] = score(text[left:right])
    best = sorted((item for item in scored if item[2] > 0), key=lambda item: -item[2])[:8]
    for width in (2, 3):
        for parts in combinations(best, width):
            ranges = _merge_spans(text, [(start, end) for start, end, _ in parts])
            # Discount redundant pieces while still allowing multiple literal
            # slices when a long unrelated paragraph separates the evidence.
            options[ranges] = max(options.get(ranges, 0), sum(item[2] for item in parts) / (1 + 0.12 * (width - 1)))
    return options


def _query_windows(text: str, start: int, end: int, terms: frozenset[str]) -> tuple[tuple[int, int], ...]:
    if end - start <= 400:
        return ()
    matches = [match for match in _WORD.finditer(text, start, end) if _stem(match.group().casefold()) in terms]
    ranges = []
    for match in matches[:24]:
        for width in (160, 320):
            left = max(start, match.start() - width // 3)
            ranges.append((left, min(end, left + width)))
    return tuple(ranges)
