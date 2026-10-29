"""Store task outcomes in real PowerContext Memory, and recall after restart."""
from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, RememberMemoryRequest, SearchMemoryRequest, open_builtin_runtime
from powercontext.builtin.scope import ScopeDraft


async def operate(directory: Path, value: dict | None) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{directory / 'memory.db'}"))
    async with open_builtin_runtime(config, scheduler_path=directory / "scheduler.db") as runtime:
        if runtime.scopes is None:
            raise RuntimeError("PowerContext scope registry is required")
        scope = await runtime.scopes.create(ScopeDraft(
            title="MiniMax SDD ticket task", summary="Ticket status filter implementation and verification",
            idempotency_key="minimax-sdd-ticket-task",
        ))
        memory = runtime.memory.for_scope(scope.scope_id)
        if value is not None:
            entry = {"recorded_at": datetime.now(timezone.utc).isoformat(), **value}
            saved = await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(
                kind="outcome", text="ticket-task " + json.dumps(entry, ensure_ascii=False),
            ),)))
            return {"operation": "write", "pid": os.getpid(), "scope_id": scope.scope_id,
                    "memory_ref": saved.memory_ref.model_dump(mode="json"), "state": entry}
        page = await memory.search(SearchMemoryRequest(query="ticket-task", mode="fts", limit=50))
        states = sorted((json.loads(hit.text.split("ticket-task ", 1)[1]) for hit in page.hits),
                        key=lambda item: item["recorded_at"])
        return {"operation": "read", "pid": os.getpid(), "scope_id": scope.scope_id,
                "states": states, "latest": states[-1] if states else None,
                "citations": [{"memory_ref": h.memory_ref.model_dump(mode="json"),
                               "entry_id": h.entry_id, "entry_version_id": h.entry_version_id} for h in page.hits]}


def main() -> None:
    request = json.load(sys.stdin)
    with redirect_stdout(sys.stderr):
        result = asyncio.run(operate(Path(request["directory"]), request.get("state")))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
