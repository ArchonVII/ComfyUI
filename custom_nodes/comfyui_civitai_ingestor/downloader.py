from __future__ import annotations

import os
import shutil
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .local_models import first_folder_path
from .store import connect, get_resource_files, utc_now


def _safe_filename(name: str) -> str:
    return Path(str(name).replace("\\", "/")).name


class DownloadManager:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def start(self, file_ids: list[int], token: str | None = None) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        conn = connect(self.db_path)
        try:
            files = get_resource_files(conn, file_ids)
        finally:
            conn.close()

        items = []
        seen_targets: set[str] = set()
        for file_info in files:
            if not file_info.get("download_url"):
                continue
            item = self._job_item(file_info)
            key = item["target_path"].lower()
            if key in seen_targets:
                continue
            seen_targets.add(key)
            items.append(item)
        free_check = self._storage_check(items)
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "storage": free_check,
            "items": items,
        }
        self.jobs[job_id] = job
        thread = threading.Thread(target=self._run_job, args=(job_id, token), daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    def _job_item(self, file_info: dict[str, Any]) -> dict[str, Any]:
        target_dir = first_folder_path(file_info["target_folder"])
        filename = _safe_filename(file_info["file_name"])
        return {
            "file_id": file_info["file_id"],
            "model_version_id": file_info["model_version_id"],
            "file_name": filename,
            "target_folder": file_info["target_folder"],
            "target_dir": target_dir,
            "target_path": str(Path(target_dir) / filename),
            "download_url": file_info["download_url"],
            "size_bytes": int(float(file_info.get("size_kb") or 0) * 1024),
            "status": "queued",
            "downloaded_bytes": 0,
            "total_bytes": int(float(file_info.get("size_kb") or 0) * 1024),
            "error": None,
        }

    def _storage_check(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        by_root: dict[str, int] = {}
        for item in items:
            by_root[item["target_dir"]] = by_root.get(item["target_dir"], 0) + int(item["size_bytes"] or 0)

        checks = []
        ok = True
        for target_dir, required in by_root.items():
            os.makedirs(target_dir, exist_ok=True)
            usage = shutil.disk_usage(target_dir)
            enough = usage.free > required
            ok = ok and enough
            checks.append(
                {
                    "target_dir": target_dir,
                    "required_bytes": required,
                    "free_bytes": usage.free,
                    "enough": enough,
                }
            )
        return {"ok": ok, "checks": checks}

    def _run_job(self, job_id: str, token: str | None) -> None:
        with self.lock:
            job = self.jobs[job_id]
            if not job["storage"]["ok"]:
                job["status"] = "blocked"
                job["updated_at"] = utc_now()
                return
            job["status"] = "running"
            job["updated_at"] = utc_now()
            for item in job["items"]:
                self._download_item(job, item, token)
            if all(item["status"] == "complete" for item in job["items"]):
                job["status"] = "complete"
            elif any(item["status"] == "failed" for item in job["items"]):
                job["status"] = "failed"
            job["updated_at"] = utc_now()

    def _download_item(self, job: dict[str, Any], item: dict[str, Any], token: str | None) -> None:
        item["status"] = "running"
        job["updated_at"] = utc_now()
        target_path = Path(item["target_path"])
        tmp_path = target_path.with_suffix(target_path.suffix + ".part")
        target_path.parent.mkdir(parents=True, exist_ok=True)

        headers = {"User-Agent": "ComfyUI-Civitai-Ingestor/0.1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(item["download_url"], headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                length = response.headers.get("Content-Length")
                if length and length.isdigit():
                    item["total_bytes"] = int(length)
                with tmp_path.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        item["downloaded_bytes"] += len(chunk)
                        job["updated_at"] = utc_now()
            tmp_path.replace(target_path)
            item["status"] = "complete"
            self._mark_downloaded(item)
        except (urllib.error.URLError, OSError, RuntimeError) as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

    def _mark_downloaded(self, item: dict[str, Any]) -> None:
        conn = connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE resource_files SET
                    local_status='present',
                    match_type='downloaded',
                    local_path=?,
                    local_folder=?,
                    updated_at=?
                WHERE file_id=?
                """,
                (
                    item["target_path"],
                    item["target_folder"],
                    utc_now(),
                    item["file_id"],
                ),
            )
            conn.commit()
        finally:
            conn.close()


download_manager = DownloadManager()
