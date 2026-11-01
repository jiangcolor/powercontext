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

"""Paper artifact family for literature management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Literal, Union

from pydantic import BaseModel, Field

from powercontext.artifacts import Artifact, ArtifactDraft, ArtifactRef

PaperSearchMode = Literal["fts", "vector", "hybrid"]


class PaperContent(BaseModel):
    """Immutable content of a Paper artifact."""

    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    methods: str | None = None
    contributions: str | None = None
    conclusions: str | None = None
    references: list[str] = Field(default_factory=list)
    topic_cluster: str | None = None
    pdf_path: str | None = None
    tags: list[str] = Field(default_factory=list)
    is_relevant: bool = False
    is_duplicate: bool = False
    duplicate_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    model_config = {"frozen": False}


class Paper(Artifact[PaperContent]):
    """A Paper artifact representing one academic publication."""

    family: ClassVar[Literal["paper"]] = "paper"


class PaperDraft(ArtifactDraft[PaperContent]):
    """Draft content and evidence for writing a Paper artifact."""

    family: ClassVar[Literal["paper"]] = "paper"


@dataclass(frozen=True)
class PaperQuery:
    """Search query for papers."""

    text: str
    mode: PaperSearchMode = "hybrid"
    limit: int = 10
    cluster: str | None = None
    is_relevant: bool | None = None


@dataclass(frozen=True)
class PaperSearchResult:
    """One paper returned by a search."""

    paper: Paper
    score: float
    matched_by: Literal["fts", "vector", "hybrid"]


@dataclass
class PaperStoreState:
    """Mutable runtime state for the paper store."""

    papers_by_id: dict[str, Paper] = field(default_factory=dict)
    cluster_index: dict[str, set[str]] = field(default_factory=dict)
