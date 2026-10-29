from __future__ import annotations

from pydantic import BaseModel


class ExperimentCreate(BaseModel):
    project_id: str
    title: str
    parameters: dict = {}
    metrics: dict = {}
    notes: str = ""
    tags: list[str] = []
    status: str = "success"
    date: str | None = None


class ExperimentResponse(BaseModel):
    id: str
    project_id: str
    title: str
    parameters: dict
    metrics: dict
    notes: str
    tags: list[str]
    status: str
    date: str
    distance: float | None = None


class SearchRequest(BaseModel):
    query: str
    project_id: str | None = None
    limit: int = 10


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    goal: str = ""


class ProjectUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
