from __future__ import annotations

import json
import uuid
from datetime import datetime

import pyseekdb

from .config import settings


class SeekDB:
    def __init__(self):
        self.client = pyseekdb.Client(path=settings.seekdb_path)
        self.collection = self.client.get_or_create_collection(
            name=settings.seekdb_collection,
        )

    def _build_document(self, title: str, notes: str, tags: list[str]) -> str:
        parts = [title]
        if notes:
            parts.append(notes)
        if tags:
            parts.append(" ".join(f"#{t}" for t in tags))
        return "\n".join(parts)

    def _build_metadata(
        self,
        project_id: str,
        parameters: dict,
        metrics: dict,
        status: str,
        tags: list[str],
        date: str,
    ) -> dict:
        return {
            "project_id": project_id,
            "parameters": json.dumps(parameters, ensure_ascii=False),
            "metrics": json.dumps(metrics, ensure_ascii=False),
            "status": status,
            "tags": json.dumps(tags, ensure_ascii=False),
            "date": date,
        }

    def add_experiment(
        self,
        project_id: str,
        title: str,
        parameters: dict,
        metrics: dict,
        notes: str,
        tags: list[str],
        status: str,
        date: str | None = None,
    ) -> str:
        exp_id = str(uuid.uuid4())
        date = date or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        document = self._build_document(title, notes, tags)
        metadata = self._build_metadata(project_id, parameters, metrics, status, tags, date)
        self.collection.upsert(ids=[exp_id], documents=[document], metadatas=[metadata])
        return exp_id

    def search(
        self,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        query_params: dict = {
            "query_texts": query,
            "n_results": limit * 2 if project_id else limit,
        }
        results = self.collection.query(**query_params)
        experiments = []
        if results and results.get("ids") and results["ids"][0]:
            for i, exp_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results.get("distances") else None
                doc = results["documents"][0][i] if results.get("documents") else ""
                if project_id and meta.get("project_id") != project_id:
                    continue
                experiments.append({
                    "id": exp_id,
                    "document": doc,
                    "metadata": meta,
                    "distance": distance,
                })
                if len(experiments) >= limit:
                    break
        return experiments

    def get_all_experiments(self, project_id: str | None = None) -> list[dict]:
        query_params: dict = {"query_texts": "experiment", "n_results": 100}
        results = self.collection.query(**query_params)
        experiments = []
        if results and results.get("ids") and results["ids"][0]:
            for i, exp_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                if project_id and meta.get("project_id") != project_id:
                    continue
                experiments.append({
                    "id": exp_id,
                    "metadata": meta,
                    "document": results["documents"][0][i] if results.get("documents") else "",
                })
        return experiments

    def delete_experiment(self, exp_id: str) -> bool:
        try:
            self.collection.delete(ids=[exp_id])
            return True
        except Exception:
            return False


db = SeekDB()
