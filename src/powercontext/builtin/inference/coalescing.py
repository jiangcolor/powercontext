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

"""Coalesce concurrent embedding requests and cache successful vectors."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from powercontext.builtin.inference.models import EmbeddingResult, InferenceUsage

DEFAULT_MAX_BATCH_SIZE = 64
DEFAULT_COALESCE_MS = 5.0
DEFAULT_CACHE_SIZE = 1024


@dataclass(slots=True)
class _Pending:
    """One text awaiting its batch result, shared by every concurrent caller."""

    future: asyncio.Future[tuple[float, ...]]
    batch_id: int | None = None
    usage: InferenceUsage | None = field(default=None)


class CoalescingEmbeddingModel:
    """Share in-flight embeddings across callers and cache successful vectors."""

    def __init__(
        self,
        model: Any,
        /,
        *,
        max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
        coalesce_ms: float = DEFAULT_COALESCE_MS,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        if isinstance(coalesce_ms, bool) or not isinstance(coalesce_ms, (int, float)) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a non-negative number")  # noqa: TRY003
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_ms = float(coalesce_ms)
        self._cache_size = cache_size
        self._cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._pending: dict[str, _Pending] = {}
        self._background: set[asyncio.Task[None]] = set()
        self._batch_seq = 0
        self.profile = model.profile

    async def embed(self, texts: Sequence[str], /) -> EmbeddingResult:
        texts = tuple(texts)
        if not texts:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        unique = tuple(dict.fromkeys(texts))
        resolved: dict[str, tuple[float, ...]] = {}
        awaited: list[tuple[str, _Pending]] = []
        to_start: list[str] = []
        loop = asyncio.get_running_loop()

        for text in unique:
            if self._cache_size and text in self._cache:
                self._cache.move_to_end(text)
                resolved[text] = self._cache[text]
                continue
            pending = self._pending.get(text)
            if pending is None:
                pending = _Pending(future=loop.create_future())
                self._pending[text] = pending
                to_start.append(text)
            awaited.append((text, pending))

        if to_start:
            # Hold the window open so concurrent callers can join these texts.
            if self._coalesce_ms > 0:
                await asyncio.sleep(self._coalesce_ms / 1000)
            for chunk in _chunks(to_start, self._max_batch_size):
                # Run every batch on its own task so cancelling one caller cannot
                # abort work that other callers are still waiting on.
                task = loop.create_task(self._run_batch(chunk))
                self._background.add(task)
                task.add_done_callback(self._background.discard)

        for text, pending in awaited:
            resolved[text] = await asyncio.shield(pending.future)

        return EmbeddingResult(
            vectors=tuple(resolved[text] for text in texts),
            usage=_aggregate_usage(pending for _, pending in awaited),
        )

    async def _run_batch(self, chunk: Sequence[str]) -> None:
        self._batch_seq += 1
        batch_id = self._batch_seq
        for text in chunk:
            self._pending[text].batch_id = batch_id
        try:
            result = await self._model.embed(tuple(chunk))
            if len(result.vectors) != len(chunk):
                raise ValueError("embedding provider returned a mismatched vector count")  # noqa: TRY003
            usage = result.usage
            for text, vector in zip(chunk, result.vectors, strict=True):
                if self._cache_size:
                    self._cache[text] = vector
                    self._cache.move_to_end(text)
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
        except Exception as error:  # noqa: BLE001 - propagate provider failures to every waiter
            for text in chunk:
                pending = self._pending.pop(text, None)
                if pending is not None and not pending.future.done():
                    pending.future.set_exception(error)
            return

        for text, vector in zip(chunk, result.vectors, strict=True):
            pending = self._pending.pop(text, None)
            if pending is None:
                continue
            pending.usage = usage
            if not pending.future.done():
                pending.future.set_result(vector)


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _aggregate_usage(pendings: Iterable[_Pending]) -> InferenceUsage:
    batch_ids: set[int] = set()
    requests = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    for pending in pendings:
        if pending.batch_id is None or pending.batch_id in batch_ids:
            continue
        batch_ids.add(pending.batch_id)
        usage = pending.usage
        if usage is None:
            requests += 1
            continue
        requests += usage.requests
        if usage.input_tokens is not None:
            input_tokens = (input_tokens or 0) + usage.input_tokens
        if usage.output_tokens is not None:
            output_tokens = (output_tokens or 0) + usage.output_tokens
    return InferenceUsage(requests=requests, input_tokens=input_tokens, output_tokens=output_tokens)


__all__ = [
    "DEFAULT_CACHE_SIZE",
    "DEFAULT_COALESCE_MS",
    "DEFAULT_MAX_BATCH_SIZE",
    "CoalescingEmbeddingModel",
]
