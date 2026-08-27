from __future__ import annotations

import asyncio
import json as json_module
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote, unquote

import aiohttp

from csrcqsf.core.settings import (
    reconstruction_server_download_timeout_sec,
    reconstruction_server_timeout_sec,
    reconstruction_server_url,
)
from csrcqsf.infra.external.error_response import format_remote_error, read_remote_error


_CONTENT_DISPOSITION_FILENAME_RE = re.compile(
    r"filename\*?\s*=\s*(?:\"([^\"]*)\"|([^;]*))",
    re.IGNORECASE,
)


def _sanitize_content_disposition(value: str | None) -> str | None:
    if not value or "\r" in value or "\n" in value:
        return None
    match = _CONTENT_DISPOSITION_FILENAME_RE.search(value)
    if match is None:
        return None
    filename = (match.group(1) or match.group(2) or "").strip()
    if "''" in filename:
        filename = filename.split("''", 1)[1]
    filename = unquote(filename).replace("\\", "/").rsplit("/", 1)[-1]
    filename = "".join(char for char in filename if char >= " " and char != '"')
    filename = filename.strip()[:255]
    if not filename:
        return None
    if not filename.isascii():
        return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
    return f'attachment; filename="{filename}"'


def _validated_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        length = int(value)
    except (TypeError, ValueError):
        return None
    return length if length >= 0 else None


@dataclass
class ReconstructionUpstreamStream:
    session: aiohttp.ClientSession
    response: aiohttp.ClientResponse
    content_type: str
    content_disposition: str | None
    content_length: int | None

    @property
    def safe_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.content_disposition:
            headers["Content-Disposition"] = self.content_disposition
        if self.content_length is not None:
            headers["Content-Length"] = str(self.content_length)
        return headers

    async def iter_bytes(self):
        try:
            async for chunk in self.response.content.iter_chunked(64 * 1024):
                yield chunk
        finally:
            self.response.close()
            await self.session.close()


class ReconstructionServiceClientError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        error_kind: str = "remote",
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.error_kind = error_kind


class ReconstructionServiceClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_sec: float | None = None,
        download_timeout_sec: float | None = None,
    ):
        self.base_url = (base_url or reconstruction_server_url).rstrip("/")
        self.timeout_sec = timeout_sec or reconstruction_server_timeout_sec
        self.download_timeout_sec = (
            download_timeout_sec or reconstruction_server_download_timeout_sec
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: Mapping[str, str] | None = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                request_kwargs = {"json": json}
                if params is not None:
                    request_kwargs["params"] = params
                async with session.request(method, url, **request_kwargs) as response:
                    if response.status >= 400:
                        detail = await read_remote_error(response)
                        raise ReconstructionServiceClientError(
                            detail,
                            status_code=response.status,
                        )
                    return await response.json()
        except ReconstructionServiceClientError:
            raise
        except asyncio.TimeoutError as exc:
            raise ReconstructionServiceClientError(
                "调用重构服务超时",
                error_kind="timeout",
            ) from exc
        except (aiohttp.ClientConnectionError, aiohttp.ClientError) as exc:
            raise ReconstructionServiceClientError(
                "无法连接重构服务",
                error_kind="connection",
            ) from exc
        except Exception as exc:
            raise ReconstructionServiceClientError("调用重构服务失败") from exc

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

    async def get_recovery_plan(self, task_id: str) -> dict:
        return await self._request(
            "GET",
            f"/reconstruction/tasks/{task_id}/recovery/plan",
            json=None,
            params=None,
        )

    async def submit_recovery(self, task_id: str, payload: dict) -> dict:
        return await self._request(
            "POST",
            f"/reconstruction/tasks/{task_id}/recovery",
            json=payload,
            params=None,
        )

    async def get_diagnostics(self, task_id: str) -> dict:
        return await self._request(
            "GET",
            f"/reconstruction/tasks/{task_id}/diagnostics",
            json=None,
            params=None,
        )

    async def delete_task_output(self, task_id: str, *, confirm: bool) -> dict:
        return await self._request(
            "DELETE",
            f"/reconstruction/tasks/{task_id}/output",
            json=None,
            params={"confirm": str(confirm).lower()},
        )

    async def _open_stream(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> ReconstructionUpstreamStream:
        url = f"{self.base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=self.download_timeout_sec)
        session = aiohttp.ClientSession(timeout=timeout)
        response = None
        try:
            request_kwargs = {}
            if params is not None:
                request_kwargs["params"] = params
            response = await session.request("GET", url, **request_kwargs)
            if response.status >= 400:
                body = await response.content.read(8192)
                try:
                    payload = json_module.loads(body.decode("utf-8", errors="replace"))
                except (json_module.JSONDecodeError, UnicodeDecodeError):
                    payload = body.decode("utf-8", errors="replace")
                raise ReconstructionServiceClientError(
                    format_remote_error(payload),
                    status_code=response.status,
                )

            raw_content_type = response.headers.get(
                "Content-Type",
                "application/octet-stream",
            )
            content_type = (
                "application/octet-stream"
                if "\r" in raw_content_type or "\n" in raw_content_type
                else raw_content_type
            )
            # aiohttp 默认解压带 Content-Encoding 的正文，原始压缩长度不能继续下发。
            content_length = (
                None
                if response.headers.get("Content-Encoding")
                else _validated_content_length(response.headers.get("Content-Length"))
            )
            return ReconstructionUpstreamStream(
                session=session,
                response=response,
                content_type=content_type,
                content_disposition=_sanitize_content_disposition(
                    response.headers.get("Content-Disposition")
                ),
                content_length=content_length,
            )
        except ReconstructionServiceClientError:
            if response is not None:
                response.close()
            await session.close()
            raise
        except asyncio.TimeoutError as exc:
            if response is not None:
                response.close()
            await session.close()
            raise ReconstructionServiceClientError(
                "下载重构文件超时",
                error_kind="timeout",
            ) from exc
        except (aiohttp.ClientConnectionError, aiohttp.ClientError) as exc:
            if response is not None:
                response.close()
            await session.close()
            raise ReconstructionServiceClientError(
                "无法连接重构服务",
                error_kind="connection",
            ) from exc
        except Exception as exc:
            if response is not None:
                response.close()
            await session.close()
            raise ReconstructionServiceClientError("下载重构文件失败") from exc

    async def stream_task_log(self, task_id: str) -> ReconstructionUpstreamStream:
        return await self._open_stream(
            f"/reconstruction/tasks/{task_id}/logs/download"
        )

    async def stream_diagnostic_artifact(
        self,
        task_id: str,
        relative_path: str,
    ) -> ReconstructionUpstreamStream:
        return await self._open_stream(
            f"/reconstruction/tasks/{task_id}/diagnostics/artifacts/download",
            params={"path": relative_path},
        )

    async def stream_diagnostics_archive(
        self,
        task_id: str,
    ) -> ReconstructionUpstreamStream:
        return await self._open_stream(
            f"/reconstruction/tasks/{task_id}/diagnostics/download"
        )
