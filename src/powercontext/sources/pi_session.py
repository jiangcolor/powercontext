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

"""Capture the selected Pi session branch as immutable per-event evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    ConnectorSubmissionStatus,
)
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_NAME = "pi-event"
PI_EVENT_SOURCE_VERSION = "1"
PI_EVENT_CONNECTOR_NAME = "pi-session-history"
PI_EVENT_CONNECTOR_VERSION = "1"

_CONTROL_TYPES = frozenset(
    {
        "session",
        "model_change",
        "thinking_level_change",
        "compaction_trigger",
        "branch_switch",
        "label",
        "permission_change",
    }
)


class PiSessionInput(BaseModel):
    """One complete Pi session archive plus the branch leaf to capture."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected branch, retaining the raw record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


class PiEventSource(Source):
    """A captured Pi event Source whose identity is the session plus event."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Build the stable ``pi-event:<session>:<event>`` identity for one event."""

    source_id = f"{PI_EVENT_SOURCE_NAME}:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"pi event identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def parse_pi_session(value: PiSessionInput, /) -> tuple[PiEventInput, ...]:
    """Parse the selected branch and return every visible event from root to leaf."""

    try:
        text = value.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("pi session archive must be valid UTF-8") from error

    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as error:
            raise ValueError("pi session archive contains malformed JSON") from error
        if not isinstance(record, dict):
            raise ValueError("pi session records must be JSON objects")  # noqa: TRY003
        records.append(record)

    if not records:
        raise ValueError("pi session archive must contain a session header")  # noqa: TRY003

    header = records[0]
    if header.get("type") != "session":
        raise ValueError("pi session archive must start with a session header")  # noqa: TRY003
    if header.get("version") != 3:
        raise ValueError("pi session archive must declare version 3")  # noqa: TRY003
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("pi session header must declare a non-empty id")  # noqa: TRY003

    parents: dict[str, str | None] = {}
    order: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for record in records[1:]:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("pi session records must declare a non-empty id")  # noqa: TRY003
        if event_id in by_id:
            raise ValueError(f"pi session record id {event_id!r} is duplicated")  # noqa: TRY003
        parent_id = record.get("parentId")
        if parent_id is not None:
            if not isinstance(parent_id, str):
                raise ValueError("pi session parentId must be a string or null")  # noqa: TRY003
            if parent_id == event_id:
                raise ValueError("pi session record cannot be its own parent")  # noqa: TRY003
            if parent_id not in by_id:
                raise ValueError(f"pi session parent {parent_id!r} does not exist")  # noqa: TRY003
        by_id[event_id] = record
        parents[event_id] = parent_id
        order.append(event_id)

    if not order:
        raise ValueError("pi session archive must contain at least one record")  # noqa: TRY003

    leaf = value.leaf_id if value.leaf_id is not None else order[-1]
    if leaf not in by_id:
        raise ValueError(f"pi session leaf {leaf!r} does not exist")  # noqa: TRY003

    chain: list[str] = []
    cursor: str | None = leaf
    while cursor is not None:
        chain.append(cursor)
        cursor = parents[cursor]
    chain.reverse()

    events: list[PiEventInput] = []
    for event_id in chain:
        record = by_id[event_id]
        parsed = _visible_event(session_id, event_id, parents[event_id], record)
        if parsed is not None:
            events.append(parsed)
    return tuple(events)


def _visible_event(
    session_id: str,
    event_id: str,
    parent_id: str | None,
    record: dict[str, Any],
) -> PiEventInput | None:
    event_type = record.get("type")
    if not isinstance(event_type, str):
        raise ValueError("pi session records must declare a type")  # noqa: TRY003

    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            raise ValueError("pi session message records must declare a message")  # noqa: TRY003
        role = message.get("role")
        if not isinstance(role, str) or not role.strip():
            raise ValueError("pi session message records must declare a role")  # noqa: TRY003
        body = _message_body(role, message)
        if body is None:
            return None
        return PiEventInput(
            session_id=session_id,
            event_id=event_id,
            parent_id=parent_id,
            event_type=event_type,
            role=role,
            content=f"{role}: {body}",
            record=record,
        )

    if event_type in {"compaction", "branch_summary"}:
        summary = record.get("summary")
        if not isinstance(summary, str):
            raise ValueError(f"pi session {event_type} records must declare a summary")  # noqa: TRY003
        return PiEventInput(
            session_id=session_id,
            event_id=event_id,
            parent_id=parent_id,
            event_type=event_type,
            role=event_type,
            content=f"{event_type}: {summary}",
            record=record,
        )

    if event_type == "custom_message":
        body = _blocks_text(record.get("content"))
        if body is None:
            return None
        return PiEventInput(
            session_id=session_id,
            event_id=event_id,
            parent_id=parent_id,
            event_type=event_type,
            role="custom",
            content=f"custom: {body}",
            record=record,
        )

    if event_type in _CONTROL_TYPES:
        return None
    return None


def _message_body(role: str, message: dict[str, Any]) -> str | None:
    if role == "toolResult":
        tool_name = message.get("toolName", "")
        tool_call_id = message.get("toolCallId", "")
        text = _blocks_text(message.get("content"), join="") or ""
        return f"[tool_result {tool_name} {tool_call_id}] {text}"
    if role == "bashExecution":
        command = message.get("command", "")
        output = message.get("output", "")
        return f"$ {command}\n{output}"
    return _blocks_text(message.get("content"))


def _blocks_text(content: Any, *, join: str = "\n") -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        elif block_type == "toolCall":
            name = block.get("name", "")
            call_id = block.get("id", "")
            arguments = block.get("arguments", {})
            encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            parts.append(f"[tool_call {name} {call_id}] {encoded}")
    return join.join(parts) if parts else None


class _PiEventAdapter:
    """Resolve and read Pi event values without touching a catalog."""

    input_class = PiEventInput
    source_class = PiEventSource
    name = PI_EVENT_SOURCE_NAME

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class _PiEventTextEvidence:
    """Project one event into the standard text-evidence shape."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = AdapterSourceDefinition(
    adapter=_PiEventAdapter(),
    version=PI_EVENT_SOURCE_VERSION,
    projections=(_PiEventTextEvidence(),),
)


class PiSessionConnector:
    """Tail one Pi session file and submit only newly visible branch evidence."""

    name = PI_EVENT_CONNECTOR_NAME
    version = PI_EVENT_CONNECTOR_VERSION
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    def with_leaf(self, leaf_id: str | None) -> PiSessionConnector:
        return PiSessionConnector(self._path, leaf_id)

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        events = parse_pi_session(PiSessionInput(content=self._path.read_bytes(), leaf_id=self._leaf_id))
        checkpoint = session.checkpoint or {}
        seen = checkpoint.get("events") if isinstance(checkpoint, dict) else None
        recorded: dict[str, str] = dict(seen) if isinstance(seen, dict) else {}

        for event in events:
            previous = recorded.get(event.event_id)
            if previous is not None and previous != _fingerprint(event):
                raise ValueError(f"pi session event {event.event_id!r} changed after capture")  # noqa: TRY003

        for event in events:
            if event.event_id in recorded:
                continue
            outcome = await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            if outcome.status is ConnectorSubmissionStatus.ACCEPTED:
                recorded[event.event_id] = _fingerprint(event)

        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"events": recorded},
        )


def _fingerprint(event: PiEventInput) -> str:
    encoded = json.dumps(event.record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PI_EVENT_CONNECTOR_NAME",
    "PI_EVENT_CONNECTOR_VERSION",
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
