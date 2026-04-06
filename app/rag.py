"""Outline -> LightRAG 同步逻辑。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import config
from database import fetch_all, postgres_connection
from lightrag_runtime import get_runtime
from outline_client import outline_export_doc, outline_list_docs

logger = logging.getLogger(__name__)

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


def _manifest_workspace() -> str:
    return config.LIGHTRAG_WORKSPACE or "default"


async def _load_manifest() -> dict[str, dict[str, Any]]:
    rows = await fetch_all(
        """
        SELECT outline_id, doc_id, file_source, title, updated_at
        FROM outline_sync_manifest
        WHERE workspace = $1
        """,
        _manifest_workspace(),
    )
    return {
        str(row["outline_id"]): {
            "doc_id": str(row["doc_id"]),
            "file_source": str(row["file_source"] or ""),
            "title": str(row["title"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }
        for row in rows
    }


async def _save_manifest(manifest: dict[str, dict[str, Any]]) -> None:
    workspace = _manifest_workspace()
    async with postgres_connection() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM outline_sync_manifest WHERE workspace = $1",
                workspace,
            )
            if manifest:
                await conn.executemany(
                    """
                    INSERT INTO outline_sync_manifest (
                        workspace,
                        outline_id,
                        doc_id,
                        file_source,
                        title,
                        updated_at,
                        synced_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
                    """,
                    [
                        (
                            workspace,
                            outline_id,
                            str(entry.get("doc_id") or _stable_doc_id(outline_id)),
                            str(entry.get("file_source") or ""),
                            str(entry.get("title") or ""),
                            str(entry.get("updated_at") or ""),
                        )
                        for outline_id, entry in manifest.items()
                    ],
                )


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


def get_refresh_state() -> dict[str, Any]:
    return dict(_refresh_state)


async def refresh_all_task() -> None:
    async with _refresh_lock:
        runtime = get_runtime()
        rag = runtime.rag
        manifest = await _load_manifest()
        next_manifest: dict[str, dict[str, Any]] = {}
        started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")

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
            _refresh_state["total"] = len(remote_docs_by_id)

            deleted = 0
            for outline_id, old_entry in manifest.items():
                if outline_id in remote_docs_by_id:
                    continue
                doc_id = str(old_entry.get("doc_id") or _stable_doc_id(outline_id))
                try:
                    await rag.adelete_by_doc_id(doc_id)
                    deleted += 1
                except Exception as exc:
                    logger.warning("删除已移除 Outline 文档失败 %s: %s", outline_id, exc)

            texts_to_insert: list[str] = []
            ids_to_insert: list[str] = []
            file_paths_to_insert: list[str] = []
            processed = 0
            skipped = 0

            for outline_id, doc in remote_docs_by_id.items():
                stable_doc_id = _stable_doc_id(outline_id)
                remote_updated_at = str(doc.get("updatedAt") or "")
                file_source = _resolve_outline_file_source(doc)
                previous = manifest.get(outline_id)
                existing_doc = await rag.full_docs.get_by_id(stable_doc_id)

                if (
                    previous
                    and previous.get("updated_at") == remote_updated_at
                    and existing_doc
                ):
                    next_manifest[outline_id] = previous
                    skipped += 1
                    continue

                content = await outline_export_doc(outline_id)
                if not content or not content.strip():
                    if existing_doc:
                        await rag.adelete_by_doc_id(stable_doc_id)
                        deleted += 1
                    skipped += 1
                    continue

                if existing_doc:
                    await rag.adelete_by_doc_id(stable_doc_id)

                texts_to_insert.append(content)
                ids_to_insert.append(stable_doc_id)
                file_paths_to_insert.append(file_source)
                next_manifest[outline_id] = {
                    "doc_id": stable_doc_id,
                    "file_source": file_source,
                    "title": doc.get("title") or "",
                    "updated_at": remote_updated_at,
                }
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

            await _save_manifest(next_manifest)

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
            return


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
