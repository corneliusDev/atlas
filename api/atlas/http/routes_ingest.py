"""Ingest routes: uploads (UP-2/3/7), vault scan (UP-1), recluster (TP-3), progress tray (UP-4).

The API never parses or indexes: uploads are validated (extension, path, size), written to the
uploads volume and turned into one ``Upsert(origin="upload")`` job each. Everything else is
the worker's job (PRD Output 4).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from atlas.http.dto import (
    AcceptedFile,
    JobsStatusResponse,
    ReclusterResponse,
    ScanResponse,
    UploadResponse,
)
from atlas.http.routes_common import (
    ERR,
    UploadConfig,
    VaultParam,
    get_hash_lookup,
    get_jobs_reader,
    get_queue,
    get_scanner,
    get_upload_config,
    get_vault_reader,
    need,
    require_vault,
)
from atlas.ports import JobQueue, VaultScanner
from atlas.read.protocols import ContentHashLookup, JobsStatusReader, VaultReader
from atlas.types import (
    DEFAULT_VAULT_ID,
    MARKDOWN_SUFFIXES,
    ContentHash,
    IgnoredFile,
    Recluster,
    Upsert,
    VaultId,
    VaultPath,
    parse_vault_path,
)

router = APIRouter()


# ---- upload intake (pure-ish: bytes in, accepted/ignored out) ---------------------------
@dataclass
class _Intake:
    files: list[tuple[VaultPath, bytes]] = field(default_factory=list)
    ignored: list[IgnoredFile] = field(default_factory=list)

    def offer(self, raw_name: str, read: "_Reader", declared_size: int | None, max_bytes: int) -> None:
        """Validate one candidate file; ``read(n)`` returns at most n bytes of its content."""
        name = raw_name.replace("\\", "/")
        if PurePosixPath(name).suffix.lower() not in MARKDOWN_SUFFIXES:
            self.ignored.append(IgnoredFile(path=raw_name, reason="not_markdown"))
            return
        path = parse_vault_path(name)
        if path is None:
            self.ignored.append(IgnoredFile(path=raw_name, reason="invalid_path"))
            return
        if declared_size is not None and declared_size > max_bytes:
            self.ignored.append(IgnoredFile(path=raw_name, reason="too_large"))
            return
        data = read(max_bytes + 1)
        if len(data) > max_bytes:
            self.ignored.append(IgnoredFile(path=raw_name, reason="too_large"))
            return
        self.files.append((path, data))


class _Reader:
    def __init__(self, fh: IO[bytes]) -> None:
        self._fh = fh

    def __call__(self, n: int) -> bytes:
        return self._fh.read(n)


def _take_zip(intake: _Intake, upload_name: str, fh: IO[bytes], max_bytes: int) -> None:
    try:
        zf = zipfile.ZipFile(fh)
    except (zipfile.BadZipFile, OSError):
        intake.ignored.append(IgnoredFile(path=upload_name, reason="invalid_path"))
        return
    with zf:
        for info in zf.infolist():
            if info.is_dir() or info.filename.startswith("__MACOSX/"):
                continue
            try:
                with zf.open(info) as member:
                    intake.offer(info.filename, _Reader(member), info.file_size, max_bytes)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError):
                intake.ignored.append(IgnoredFile(path=info.filename, reason="invalid_path"))


def _write_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".upload-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _destination(root: Path, vault: VaultId, path: VaultPath) -> Path:
    base = (root / str(vault)).resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base):  # parse_vault_path already rejects "..": belt and braces
        raise HTTPException(status_code=400, detail=f"invalid path: {path}")
    return target


@router.post("/api/uploads", response_model=UploadResponse, responses=ERR, tags=["ingest"],
             summary="Upload .md/.markdown files or a .zip; one Upsert(origin=upload) job per file")
def upload(
    files: Annotated[list[UploadFile], File(description=".md, .markdown or .zip files")],
    queue: Annotated[JobQueue | None, Depends(get_queue)],
    config: Annotated[UploadConfig | None, Depends(get_upload_config)],
    hashes: Annotated[ContentHashLookup | None, Depends(get_hash_lookup)],
    vaults: Annotated[VaultReader | None, Depends(get_vault_reader)],
    vault: Annotated[UUID, Form()] = DEFAULT_VAULT_ID,
) -> UploadResponse:
    q = need(queue, "upload")
    cfg = need(config, "upload")
    vid = VaultId(vault)
    require_vault(vaults, vid)

    intake = _Intake()
    for f in files:
        name = f.filename or ""
        if name.lower().endswith(".zip"):
            _take_zip(intake, name, f.file, cfg.max_file_bytes)
        else:
            intake.offer(name, _Reader(f.file), f.size, cfg.max_file_bytes)

    accepted: list[AcceptedFile] = []
    for path, data in intake.files:
        _write_atomic(_destination(cfg.root, vid, path), data)
        digest = ContentHash(hashlib.sha256(data).hexdigest())
        unchanged = hashes is not None and hashes.current_hash(vid, path) == digest
        job_id = q.enqueue(Upsert(vault=vid, path=path, origin="upload"))
        accepted.append(AcceptedFile(path=path, job_id=job_id, unchanged=unchanged))
    return UploadResponse(vault=vid, accepted=accepted, ignored=intake.ignored)


@router.post("/api/vaults/{vault_id}/scan", response_model=ScanResponse, responses=ERR, tags=["ingest"])
def scan(
    vault_id: UUID,
    scanner: Annotated[VaultScanner | None, Depends(get_scanner)],
    vaults: Annotated[VaultReader | None, Depends(get_vault_reader)],
) -> ScanResponse:
    s = need(scanner, "scan")
    require_vault(vaults, VaultId(vault_id))
    return s.scan(VaultId(vault_id))


@router.post("/api/vaults/{vault_id}/recluster", response_model=ReclusterResponse, responses=ERR, tags=["ingest"])
def recluster(
    vault_id: UUID,
    queue: Annotated[JobQueue | None, Depends(get_queue)],
    vaults: Annotated[VaultReader | None, Depends(get_vault_reader)],
) -> ReclusterResponse:
    q = need(queue, "recluster")
    vid = VaultId(vault_id)
    require_vault(vaults, vid)
    return ReclusterResponse(vault=vid, job_id=q.enqueue(Recluster(vault=vid)))


@router.get("/api/jobs/status", response_model=JobsStatusResponse, tags=["ingest"],
            summary="Progress tray: counts by state, latest job per file, recent failures")
def jobs_status(
    jobs: Annotated[JobsStatusReader | None, Depends(get_jobs_reader)],
    vault: VaultParam = DEFAULT_VAULT_ID,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> JobsStatusResponse:
    return need(jobs, "jobs status").status(VaultId(vault), limit)
