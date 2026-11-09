"""Vault list read model: GET /api/vaults, plus the existence check routes use for 404s."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from atlas.http.dto import VaultDto
from atlas.read.db import Connect, fetch_all, fetch_one
from atlas.types import VaultId


def is_mounted(root: Path) -> bool:
    try:
        return root.is_dir() and any(root.iterdir())
    except OSError:
        return False


@dataclass
class PgVaultReader:
    """Implements ``atlas.read.protocols.VaultReader``. ``vault_roots`` maps a vault id to the
    path this process sees (e.g. settings.vault_root for the default vault); otherwise
    vaults.root_path is used for the ``mounted`` check."""

    connect: Connect
    vault_roots: dict[VaultId, Path] = field(default_factory=dict)

    def vaults(self) -> list[VaultDto]:
        with self.connect() as conn:
            rows = fetch_all(
                conn,
                "SELECT v.id, v.name, v.root_path, count(d.id) AS n FROM vaults v"
                " LEFT JOIN documents d ON d.vault_id = v.id"
                " GROUP BY v.id ORDER BY v.created_at, v.id",
            )
        return [
            VaultDto(
                id=VaultId(r["id"]),
                name=r["name"],
                root_path=r["root_path"],
                mounted=is_mounted(self.vault_roots.get(VaultId(r["id"])) or Path(r["root_path"])),
                document_count=int(r["n"]),
            )
            for r in rows
        ]

    def exists(self, vault: VaultId) -> bool:
        with self.connect() as conn:
            return fetch_one(conn, "SELECT 1 AS x FROM vaults WHERE id = %s", (vault,)) is not None
