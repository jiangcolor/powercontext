from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .database import db
from .models import (
    ExperimentCreate,
    ExperimentResponse,
    ProjectCreate,
    ProjectUpdate,
    SearchRequest,
)
from .powercontext import pc_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="实验记录本 API",
    description="基于 seekdb + PowerContext 的智能实验记录与检索系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_metadata(meta: dict) -> dict:
    def _safe_json(value, default):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return default
        return value or default

    return {
        "id": meta.get("id", ""),
        "project_id": meta.get("project_id", ""),
        "title": meta.get("title", ""),
        "parameters": _safe_json(meta.get("parameters"), {}),
        "metrics": _safe_json(meta.get("metrics"), {}),
        "notes": meta.get("notes", ""),
        "tags": _safe_json(meta.get("tags"), []),
        "status": meta.get("status", "success"),
        "date": meta.get("date", ""),
    }


# ── 实验记录 ─────────────────────────────────────────────


@app.post("/api/experiments", response_model=ExperimentResponse)
async def create_experiment(exp: ExperimentCreate):
    exp_id = db.add_experiment(
        project_id=exp.project_id,
        title=exp.title,
        parameters=exp.parameters,
        metrics=exp.metrics,
        notes=exp.notes,
        tags=exp.tags,
        status=exp.status,
        date=exp.date,
    )
    return ExperimentResponse(
        id=exp_id,
        project_id=exp.project_id,
        title=exp.title,
        parameters=exp.parameters,
        metrics=exp.metrics,
        notes=exp.notes,
        tags=exp.tags,
        status=exp.status,
        date=exp.date or "",
    )


@app.get("/api/experiments")
async def list_experiments(project_id: str | None = None):
    experiments = db.get_all_experiments(project_id=project_id)
    return [_parse_metadata(exp.get("metadata", {})) for exp in experiments]


@app.delete("/api/experiments/{exp_id}")
async def delete_experiment(exp_id: str):
    success = db.delete_experiment(exp_id)
    if not success:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return {"status": "deleted"}


# ── 语义搜索 (seekdb) ────────────────────────────────────


@app.post("/api/search")
async def search_experiments(req: SearchRequest):
    results = db.search(query=req.query, project_id=req.project_id, limit=req.limit)
    experiments = []
    for r in results:
        parsed = _parse_metadata(r.get("metadata", {}))
        parsed["distance"] = r.get("distance")
        experiments.append(parsed)
    return experiments


# ── 项目管理 (PowerContext) ───────────────────────────────


@app.post("/api/projects")
async def create_project(project: ProjectCreate):
    try:
        result = await pc_client.remember(
            key=f"project:{project.name}",
            content=f"项目名称: {project.name}\n描述: {project.description}\n目标: {project.goal}",
            category="project",
        )
        return {"name": project.name, "description": project.description, "goal": project.goal, "status": "active", "memory": result}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"PowerContext 服务不可用: {e}")


@app.get("/api/projects")
async def list_projects():
    try:
        memories = await pc_client.list_memories()
        projects = []
        if isinstance(memories, list):
            for m in memories:
                if m.get("category") == "project":
                    projects.append(m)
        return projects if projects else memories
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"PowerContext 服务不可用: {e}")


@app.post("/api/projects/{project_name}/update")
async def update_project(project_name: str, update: ProjectUpdate):
    try:
        content_parts = [f"项目: {project_name}"]
        if update.status:
            content_parts.append(f"状态: {update.status}")
        if update.notes:
            content_parts.append(f"备注: {update.notes}")
        result = await pc_client.remember(
            key=f"project:{project_name}:update",
            content="\n".join(content_parts),
            category="project_update",
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"PowerContext 服务不可用: {e}")


@app.get("/api/context")
async def get_context():
    try:
        context = await pc_client.get_context()
        return context
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"PowerContext 服务不可用: {e}")


# ── 统计 ─────────────────────────────────────────────────


@app.get("/api/stats")
async def get_stats():
    experiments = db.get_all_experiments()
    project_ids = set()
    for exp in experiments:
        meta = exp.get("metadata", {})
        pid = meta.get("project_id")
        if pid:
            project_ids.add(pid)
    return {
        "total_experiments": len(experiments),
        "total_projects": len(project_ids),
    }


@app.get("/api/health")
async def health_check():
    seekdb_ok = True
    pc_ok = True
    try:
        db.get_all_experiments()
    except Exception:
        seekdb_ok = False
    try:
        await pc_client.list_memories()
    except Exception:
        pc_ok = False
    return {"seekdb": seekdb_ok, "powercontext": pc_ok}
