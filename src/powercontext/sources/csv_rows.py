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

"""Capture offline CSV rows as per-row evidence Sources."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

CSV_ROW_SOURCE_NAME = "csv-row"
CSV_ROW_SOURCE_VERSION = "1"


class CSVDocumentInput(BaseModel):
    """A complete offline CSV document addressed by one primary key column."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One parsed CSV row that keeps its header order and raw string values."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """A captured row Source whose identity is the document plus primary key."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Build the stable ``csv:<document>:<key>`` identity for one row."""

    _require_trimmed(document_id, "document_id")
    if not primary_key_value or not primary_key_value.strip():
        raise ValueError("primary_key_value must be a non-blank string")  # noqa: TRY003
    source_id = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"csv row identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and fully validate one CSV document before returning any row."""

    _require_trimmed(value.document_id, "document_id")
    if not value.primary_key or not value.primary_key.strip():
        raise ValueError("primary_key must be a non-blank string")  # noqa: TRY003

    try:
        text = value.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("csv content must be valid UTF-8") from error

    try:
        records = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        raise ValueError(f"csv content is malformed: {error}") from error

    if not records:
        raise ValueError("csv document must contain a header record")  # noqa: TRY003

    header = records[0]
    if not header:
        raise ValueError("csv header must not be empty")  # noqa: TRY003

    seen_columns: set[str] = set()
    for column in header:
        if not column or not column.strip():
            raise ValueError("csv header fields must be non-blank")  # noqa: TRY003
        if column in seen_columns:
            raise ValueError(f"csv header field {column!r} is duplicated")  # noqa: TRY003
        seen_columns.add(column)

    if value.primary_key not in seen_columns:
        raise ValueError(f"primary_key {value.primary_key!r} is not a csv header field")  # noqa: TRY003

    width = len(header)
    key_index = header.index(value.primary_key)
    columns = tuple(header)
    seen_keys: set[str] = set()
    rows: list[CSVRowInput] = []

    for record in records[1:]:
        # A completely empty physical record is skipped; a row of empty fields is not.
        if not record:
            continue
        if len(record) != width:
            raise ValueError(f"csv record has {len(record)} fields but the header declares {width}")  # noqa: TRY003
        key_value = record[key_index]
        if not key_value or not key_value.strip():
            raise ValueError("csv primary key values must be non-blank")  # noqa: TRY003
        if key_value in seen_keys:
            raise ValueError(f"csv primary key value {key_value!r} is duplicated")  # noqa: TRY003
        seen_keys.add(key_value)
        rows.append(
            CSVRowInput(
                document_id=value.document_id,
                primary_key=value.primary_key,
                primary_key_value=key_value,
                columns=columns,
                values=tuple(record),
            )
        )

    return tuple(rows)


class _CSVRowAdapter:
    """Resolve and read CSV row values without touching a catalog."""

    input_class = CSVRowInput
    source_class = CSVRowSource
    name = CSV_ROW_SOURCE_NAME

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            source_id=source_id,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class _CSVRowTextEvidence:
    """Project one row into the standard text-evidence shape."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = dict(zip(source.columns, source.values, strict=True))
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


def _require_trimmed(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")  # noqa: TRY003
    if value != value.strip():
        raise ValueError(f"{field} must not contain leading or trailing whitespace")  # noqa: TRY003


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = AdapterSourceDefinition(
    adapter=_CSVRowAdapter(),
    version=CSV_ROW_SOURCE_VERSION,
    projections=(_CSVRowTextEvidence(),),
)


__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSV_ROW_SOURCE_NAME",
    "CSV_ROW_SOURCE_VERSION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
