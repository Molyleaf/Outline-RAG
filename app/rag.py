"""Outline -> LightRAG document synchronization."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any

from . import config
from .lightrag_runtime import get_runtime
from .outline_client import outline_export_doc, outline_list_docs
from lightrag.base import DocStatus

logger = logging.getLogger(__name__)

_OUTLINE_SOURCE = "outline"
_refresh_lock = asyncio.Lock()
_refresh_task: asyncio.Task | None = None
_webhook_task: asyncio.Task | None = None
_refresh_state: dict[str, Any] = {
    "status": "idle",
    "message": "空闲",
    "started_at": None,
    "finished_at": None,
    "processed": 0,
    "skipped": 0,
    "deleted": 0,
    "total": 0,
    "track_id": None,
}


def _stable_doc_id(outline_id: str) -> str:
    return f"outline-{outline_id}"


def _resolve_outline_file_source(doc: dict[str, Any]) -> str:
    raw_url = str(doc.get("url") or "").strip()
    if not raw_url:
        return f"outline://{doc.get('id', 'unknown')}"

    display_base = config.OUTLINE_DISPLAY_URL or config.OUTLINE_API_URL
    api_base = config.OUTLINE_API_URL

    if display_base and api_base and raw_url.startswith(api_base):
        return raw_url.replace(api_base, display_base, 1)
    if display_base and raw_url.startswith("/"):
        return f"{display_base}{raw_url}"
    return raw_url


def _status_to_dict(status: Any) -> dict[str, Any] | None:
    if status is None:
        return None
    if isinstance(status, dict):
        return dict(status)
    if is_dataclass(status):
        return asdict(status)
    return {
        "content_summary": getattr(status, "content_summary", ""),
        "content_length": getattr(status, "content_length", 0),
        "file_path": getattr(status, "file_path", ""),
        "status": getattr(status, "status", None),
        "created_at": getattr(status, "created_at", None),
        "updated_at": getattr(status, "updated_at", None),
        "track_id": getattr(status, "track_id", None),
        "chunks_count": getattr(status, "chunks_count", None),
        "chunks_list": list(getattr(status, "chunks_list", []) or []),
        "error_msg": getattr(status, "error_msg", None),
        "metadata": dict(getattr(status, "metadata", {}) or {}),
    }


def _normalize_status_value(value: Any) -> str:
    if isinstance(value, DocStatus):
        return value.value
    return str(value or "")


def _doc_metadata(status_data: dict[str, Any] | None) -> dict[str, Any]:
    if not status_data:
        return {}
    metadata = status_data.get("metadata") or {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def _outline_metadata(
    doc: dict[str, Any],
    *,
    file_source: str,
    synced_at: str,
) -> dict[str, Any]:
    return {
        "source": _OUTLINE_SOURCE,
        "outline_id": str(doc.get("id") or ""),
        "outline_title": str(doc.get("title") or ""),
        "outline_updated_at": str(doc.get("updatedAt") or ""),
        "outline_url": file_source,
        "outline_synced_at": synced_at,
    }


async def _load_outline_doc_statuses() -> dict[str, dict[str, Any]]:
    runtime = get_runtime()
    statuses = (
        DocStatus.PENDING,
        DocStatus.PROCESSING,
        DocStatus.PREPROCESSED,
        DocStatus.PROCESSED,
        DocStatus.FAILED,
    )
    results = await asyncio.gather(
        *(runtime.rag.get_docs_by_status(status) for status in statuses)
    )

    outline_docs: dict[str, dict[str, Any]] = {}
    for docs_by_status in results:
        for doc_id, status in docs_by_status.items():
            status_data = _status_to_dict(status)
            metadata = _doc_metadata(status_data)
            if metadata.get("source") != _OUTLINE_SOURCE:
                continue
            outline_docs[str(doc_id)] = status_data or {}
    return outline_docs


async def _update_doc_metadata(
    doc_id: str,
    *,
    metadata: dict[str, Any],
    file_source: str,
) -> None:
    runtime = get_runtime()
    existing = _status_to_dict(await runtime.rag.doc_status.get_by_id(doc_id))
    if not existing:
        logger.warning("无法更新 Outline 元数据，文档状态不存在: %s", doc_id)
        return

    existing["metadata"] = metadata
    existing["file_path"] = file_source
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    await runtime.rag.doc_status.upsert({doc_id: existing})


def get_refresh_state() -> dict[str, Any]:
    return dict(_refresh_state)


async def refresh_all_task() -> None:
    async with _refresh_lock:
        runtime = get_runtime()
        rag = runtime.rag
        started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        synced_at = datetime.now(timezone.utc).isoformat()

        _refresh_state.update(
            {
                "status": "running",
                "message": "正在从 Outline 同步文档",
                "started_at": started_at,
                "finished_at": None,
                "processed": 0,
                "skipped": 0,
                "deleted": 0,
                "total": 0,
                "track_id": None,
            }
        )

        try:
            remote_docs = await outline_list_docs()
            if remote_docs is None:
                raise RuntimeError("无法从 Outline 拉取文档列表")

            remote_docs_by_id = {
                str(doc["id"]): doc
                for doc in remote_docs
                if doc.get("id")
            }
            local_docs = await _load_outline_doc_statuses()
            local_docs_by_outline_id = {
                str(_doc_metadata(status_data).get("outline_id") or ""): {
                    "doc_id": doc_id,
                    "status": status_data,
                }
                for doc_id, status_data in local_docs.items()
                if _doc_metadata(status_data).get("outline_id")
            }

            _refresh_state["total"] = len(remote_docs_by_id)

            deleted = 0
            for outline_id, local_entry in local_docs_by_outline_id.items():
                if outline_id in remote_docs_by_id:
                    continue
                try:
                    await rag.adelete_by_doc_id(local_entry["doc_id"])
                    deleted += 1
                except Exception as exc:
                    logger.warning("删除已移除 Outline 文档失败 %s: %s", outline_id, exc)

            texts_to_insert: list[str] = []
            ids_to_insert: list[str] = []
            file_paths_to_insert: list[str] = []
            metadata_to_update: dict[str, dict[str, Any]] = {}
            processed = 0
            skipped = 0

            for outline_id, doc in remote_docs_by_id.items():
                stable_doc_id = _stable_doc_id(outline_id)
                file_source = _resolve_outline_file_source(doc)
                remote_metadata = _outline_metadata(
                    doc,
                    file_source=file_source,
                    synced_at=synced_at,
                )
                existing_status = local_docs.get(stable_doc_id)
                existing_metadata = _doc_metadata(existing_status)
                existing_status_value = _normalize_status_value(
                    existing_status.get("status") if existing_status else None
                )
                existing_full_doc = await rag.full_docs.get_by_id(stable_doc_id)

                if (
                    existing_status
                    and existing_full_doc
                    and existing_status_value == DocStatus.PROCESSED.value
                    and existing_metadata.get("outline_updated_at")
                    == remote_metadata["outline_updated_at"]
                ):
                    if existing_metadata != remote_metadata or (
                        existing_status.get("file_path") or ""
                    ) != file_source:
                        await _update_doc_metadata(
                            stable_doc_id,
                            metadata=remote_metadata,
                            file_source=file_source,
                        )
                    skipped += 1
                    continue

                content = await outline_export_doc(outline_id)
                if not content or not content.strip():
                    if existing_status or existing_full_doc:
                        try:
                            await rag.adelete_by_doc_id(stable_doc_id)
                            deleted += 1
                        except Exception as exc:
                            logger.warning(
                                "删除空内容 Outline 文档失败 %s: %s",
                                outline_id,
                                exc,
                            )
                    skipped += 1
                    continue

                if existing_status or existing_full_doc:
                    await rag.adelete_by_doc_id(stable_doc_id)

                texts_to_insert.append(content)
                ids_to_insert.append(stable_doc_id)
                file_paths_to_insert.append(file_source)
                metadata_to_update[stable_doc_id] = remote_metadata
                processed += 1

            track_id = None
            if texts_to_insert:
                track_id = f"outline-sync-{int(time.time())}"
                await rag.ainsert(
                    texts_to_insert,
                    ids=ids_to_insert,
                    file_paths=file_paths_to_insert,
                    track_id=track_id,
                )
                for doc_id, file_source in zip(ids_to_insert, file_paths_to_insert):
                    await _update_doc_metadata(
                        doc_id,
                        metadata=metadata_to_update[doc_id],
                        file_source=file_source,
                    )

            _refresh_state.update(
                {
                    "status": "success",
                    "message": "Outline 同步完成",
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "processed": processed,
                    "skipped": skipped,
                    "deleted": deleted,
                    "track_id": track_id,
                }
            )
        except Exception as exc:
            logger.exception("Outline 同步失败: %s", exc)
            _refresh_state.update(
                {
                    "status": "error",
                    "message": f"Outline 同步失败: {exc}",
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
            )


async def request_refresh_all() -> bool:
    global _refresh_task

    if _refresh_task and not _refresh_task.done():
        return False

    _refresh_task = asyncio.create_task(refresh_all_task())
    return True


async def schedule_webhook_refresh() -> None:
    global _webhook_task

    if _webhook_task and not _webhook_task.done():
        _webhook_task.cancel()

    async def delayed_refresh():
        try:
            await asyncio.sleep(config.OUTLINE_WEBHOOK_DEBOUNCE_SECONDS)
            started = await request_refresh_all()
            if not started:
                logger.info("Webhook 延迟刷新触发时，已有同步任务在运行。")
        except asyncio.CancelledError:
            return

    _webhook_task = asyncio.create_task(delayed_refresh())


async def shutdown_background_tasks() -> None:
    global _refresh_task, _webhook_task

    for task in (_webhook_task, _refresh_task):
        if task and not task.done():
            task.cancel()

    for task in (_webhook_task, _refresh_task):
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass

    _refresh_task = None
    _webhook_task = None
