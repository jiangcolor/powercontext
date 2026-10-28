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

"""Deterministic context packs and prefix-reuse deltas for incremental transfer."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

CONTEXT_PACK_SCHEMA = "powercontext.context-pack.v1"
CONTEXT_PACK_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512

_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})


class ContextPackError(ValueError):
    """Raised when a pack, delta, or chunk boundary violates the wire contract."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_item(item: bytes) -> str:
    return base64.b64encode(item).decode("ascii")


def _decode_item(value: object) -> bytes:
    if not isinstance(value, str):
        raise ContextPackError("pack items must be base64 strings")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ContextPackError("pack item is not valid base64") from error


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("pack items must be a list")
    return tuple(_decode_item(item) for item in value)


def _unsigned_digest(items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": CONTEXT_PACK_SCHEMA, "items": [_encode_item(item) for item in items]}
    return "sha256:" + hashlib.sha256(_canonical_json(unsigned)).hexdigest()


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A complete context body split into UTF-8 safe chunks with a self-describing digest."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: Iterable[bytes], /) -> ContextPack:
        built = tuple(items)
        for item in built:
            if not isinstance(item, bytes):
                raise ContextPackError("pack items must be bytes")
        digest = _unsigned_digest(built)
        encoded = [_encode_item(item) for item in built]
        # byte_count counts the serialized payload that contains it, so solve the fixed point.
        byte_count = 0
        for _ in range(16):
            payload = {"schema": CONTEXT_PACK_SCHEMA, "items": encoded, "digest": digest, "byte_count": byte_count}
            length = len(_canonical_json(payload))
            if length == byte_count:
                return cls(items=built, digest=digest, byte_count=byte_count)
            byte_count = length
        raise ContextPackError("pack byte_count did not converge")

    @classmethod
    def from_content(cls, content: str, /, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContextPack:
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if not isinstance(content, str):
            raise ContextPackError("content must be text")
        items: list[bytes] = []
        current = bytearray()
        for character in content:
            encoded = character.encode("utf-8")
            if len(encoded) > chunk_bytes:
                raise ContextPackError("a single character does not fit the chunk budget")
            if len(current) + len(encoded) > chunk_bytes:
                items.append(bytes(current))
                current = bytearray()
            current.extend(encoded)
        if current:
            items.append(bytes(current))
        return cls.build(items)

    @classmethod
    def from_bytes(cls, data: bytes, /) -> ContextPack:
        if not isinstance(data, bytes):
            raise ContextPackError("pack payload must be bytes")
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeDecodeError) as error:
            raise ContextPackError("pack payload is not valid JSON") from error
        if not isinstance(payload, dict):
            raise ContextPackError("pack payload must be a JSON object")
        if set(payload) != _PACK_FIELDS:
            raise ContextPackError("pack payload fields do not match the wire schema")
        if payload["schema"] != CONTEXT_PACK_SCHEMA:
            raise ContextPackError("pack schema is not supported")
        items = _decode_items(payload["items"])
        digest = payload["digest"]
        if not isinstance(digest, str):
            raise ContextPackError("pack digest must be a string")
        if digest != _unsigned_digest(items):
            raise ContextPackError("pack digest does not match its items")
        byte_count = payload["byte_count"]
        if type(byte_count) is not int:
            raise ContextPackError("pack byte_count must be an integer")
        if byte_count != len(data):
            raise ContextPackError("pack byte_count does not match the payload length")
        return cls(items=items, digest=digest, byte_count=byte_count)

    def to_bytes(self) -> bytes:
        return _canonical_json(
            {
                "schema": CONTEXT_PACK_SCHEMA,
                "items": [_encode_item(item) for item in self.items],
                "digest": self.digest,
                "byte_count": self.byte_count,
            }
        )

    @property
    def text(self) -> str:
        return b"".join(self.items).decode("utf-8")


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A prefix-reuse delta that rebuilds one target pack from an identified base pack."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack, /) -> ContextPackDelta:
        limit = min(len(base.items), len(target.items))
        prefix = 0
        while prefix < limit and base.items[prefix] == target.items[prefix]:
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    @classmethod
    def from_bytes(cls, data: bytes, /) -> ContextPackDelta:
        if not isinstance(data, bytes):
            raise ContextPackError("delta payload must be bytes")
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeDecodeError) as error:
            raise ContextPackError("delta payload is not valid JSON") from error
        if not isinstance(payload, dict):
            raise ContextPackError("delta payload must be a JSON object")
        if set(payload) != _DELTA_FIELDS:
            raise ContextPackError("delta payload fields do not match the wire schema")
        if payload["schema"] != CONTEXT_PACK_DELTA_SCHEMA:
            raise ContextPackError("delta schema is not supported")
        base_digest = payload["base_digest"]
        target_digest = payload["target_digest"]
        if not isinstance(base_digest, str) or not isinstance(target_digest, str):
            raise ContextPackError("delta digests must be strings")
        prefix_items = payload["prefix_items"]
        if type(prefix_items) is not int or prefix_items < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        appended = _decode_items(payload["appended"])
        return cls(
            base_digest=base_digest,
            target_digest=target_digest,
            prefix_items=prefix_items,
            appended=appended,
        )

    def to_bytes(self) -> bytes:
        return _canonical_json(
            {
                "schema": CONTEXT_PACK_DELTA_SCHEMA,
                "base_digest": self.base_digest,
                "target_digest": self.target_digest,
                "prefix_items": self.prefix_items,
                "appended": [_encode_item(item) for item in self.appended],
            }
        )

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    """Rebuild the target pack using only the base pack and the received delta."""

    if base.digest != delta.base_digest:
        raise ContextPackError("delta was computed against a different base pack")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix exceeds the base pack length")
    rebuilt = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if rebuilt.digest != delta.target_digest:
        raise ContextPackError("delta does not rebuild the declared target digest")
    return rebuilt


__all__ = [
    "CONTEXT_PACK_DELTA_SCHEMA",
    "CONTEXT_PACK_SCHEMA",
    "DEFAULT_CHUNK_BYTES",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
