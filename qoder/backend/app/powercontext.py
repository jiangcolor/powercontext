import httpx

from .config import settings


class PowerContextClient:
    def __init__(self):
        self.base_url = settings.powercontext_url
        self.scope_name = settings.powercontext_scope
        self._scope_id = None

    async def _get_scope_id(self) -> str:
        if self._scope_id:
            return self._scope_id
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}/v1/scopes")
            resp.raise_for_status()
            scopes = resp.json()
            for scope in scopes:
                if scope.get("name") == self.scope_name:
                    self._scope_id = scope["id"]
                    return self._scope_id
            resp = await client.post(
                f"{self.base_url}/v1/scopes",
                json={"name": self.scope_name, "description": "实验记录本 - 科研项目追踪"},
            )
            resp.raise_for_status()
            scope = resp.json()
            self._scope_id = scope["id"]
            return self._scope_id

    async def remember(self, key: str, content: str, category: str = "general") -> dict:
        scope_id = await self._get_scope_id()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/v1/memory/remember",
                json={
                    "scope_id": scope_id,
                    "key": key,
                    "content": content,
                    "category": category,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def search_memory(self, query: str, limit: int = 10) -> list[dict]:
        scope_id = await self._get_scope_id()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/v1/atomic-memory/search",
                json={"scope_id": scope_id, "query": query, "limit": limit},
            )
            resp.raise_for_status()
            return resp.json()

    async def list_memories(self) -> list[dict]:
        scope_id = await self._get_scope_id()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/v1/atomic-memory/list",
                json={"scope_id": scope_id},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_context(self) -> dict:
        scope_id = await self._get_scope_id()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/v1/context/prepare",
                json={"scope_id": scope_id},
            )
            resp.raise_for_status()
            return resp.json()


pc_client = PowerContextClient()
