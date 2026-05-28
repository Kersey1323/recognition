from __future__ import annotations

import aiohttp

from csrcqsf.settings import (
    reconstruction_server_timeout_sec,
    reconstruction_server_url,
)


class ReconstructionServiceClientError(Exception):
    pass


class ReconstructionServiceClient:
    def __init__(self, base_url: str | None = None, timeout_sec: float | None = None):
        self.base_url = (base_url or reconstruction_server_url).rstrip("/")
        self.timeout_sec = timeout_sec or reconstruction_server_timeout_sec

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(method, url, json=json) as response:
                    if response.status >= 400:
                        try:
                            payload = await response.json()
                            detail = payload.get("detail") or payload.get("message") or payload
                        except Exception:
                            detail = await response.text()
                        raise ReconstructionServiceClientError(
                            f"重构服务请求失败 [{response.status}]: {detail}"
                        )
                    return await response.json()
        except ReconstructionServiceClientError:
            raise
        except Exception as exc:
            raise ReconstructionServiceClientError(f"调用重构服务失败: {exc}") from exc

    async def submit_train_task(self, payload: dict) -> dict:
        return await self._request("POST", "/reconstruction/tasks/train", json=payload)

    async def submit_video_task(self, payload: dict) -> dict:
        return await self._request("POST", "/reconstruction/tasks/video", json=payload)

    async def get_task_status(self, task_id: str) -> dict:
        return await self._request("GET", f"/reconstruction/tasks/{task_id}/status")

    async def get_task_status_batch(self, task_ids: list[str]) -> dict:
        return await self._request(
            "POST",
            "/reconstruction/tasks/status/batch",
            json={"task_ids": task_ids},
        )

    async def cancel_task(self, task_id: str) -> dict:
        return await self._request("DELETE", f"/reconstruction/tasks/{task_id}")

    async def list_scenes(self) -> dict:
        return await self._request("GET", "/reconstruction/scenes")
