from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .paths import AppPaths


class ClientSource(str, Enum):
    MANAGED = "managed"
    SYSTEM = "system"


@dataclass(frozen=True)
class DumpClient:
    source: ClientSource
    vendor: str
    dump: Path
    mysql: Path

    def describe(self) -> str:
        return f"{self.source.value}:{self.vendor} dump={self.dump} mysql={self.mysql}"


@dataclass(frozen=True)
class ResolvedEngine:
    kind: str  # dump or python
    client: DumpClient | None
    reason: str


_VENDOR_PAIRS = {
    "mariadb": [("mariadb-dump", "mariadb"), ("mysqldump", "mysql")],
    "mysql": [("mysqldump", "mysql"), ("mariadb-dump", "mariadb")],
}


def is_executable(path: Path) -> bool:
    return path.is_file() and bool(path.stat().st_mode & stat.S_IXUSR)


def exe_name(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def find_managed_client(paths: AppPaths | None = None, vendor: str = "mariadb") -> DumpClient | None:
    paths = paths or AppPaths.current()
    roots = [paths.managed_client_dir / vendor, paths.managed_client_dir]
    pairs = _VENDOR_PAIRS.get(vendor, _VENDOR_PAIRS["mariadb"])
    for root in roots:
        if not root.exists():
            continue
        for bin_dir in [root / "current" / "bin", root / "bin", root / "current", root]:
            for dump_name, mysql_name in pairs:
                dump = bin_dir / exe_name(dump_name)
                mysql = bin_dir / exe_name(mysql_name)
                if is_executable(dump) and is_executable(mysql):
                    actual_vendor = "mariadb" if "mariadb" in dump_name else "mysql"
                    return DumpClient(ClientSource.MANAGED, actual_vendor, dump, mysql)
    return None


def find_system_client(preferred_vendor: str = "mariadb") -> DumpClient | None:
    pairs = _VENDOR_PAIRS.get(preferred_vendor, _VENDOR_PAIRS["mariadb"])
    for dump_name, mysql_name in pairs:
        dump = shutil.which(dump_name)
        mysql = shutil.which(mysql_name)
        if dump and mysql:
            vendor = "mariadb" if "mariadb" in dump_name else "mysql"
            return DumpClient(ClientSource.SYSTEM, vendor, Path(dump), Path(mysql))
    return None


def resolve_client(paths: AppPaths | None = None, mode: str = "auto", preferred_source: str = "managed", vendor: str = "mariadb") -> ResolvedEngine:
    paths = paths or AppPaths.current()
    mode = (mode or "auto").lower()
    preferred_source = (preferred_source or "managed").lower()

    if mode == "python":
        return ResolvedEngine("python", None, "Modo python solicitado.")

    clients: list[DumpClient | None]
    if preferred_source == "system":
        clients = [find_system_client(vendor), find_managed_client(paths, vendor)]
    else:
        clients = [find_managed_client(paths, vendor), find_system_client(vendor)]

    for client in clients:
        if client:
            return ResolvedEngine("dump", client, f"Cliente {client.source.value} disponível ({client.vendor}).")

    if mode in {"dump", "managed-dump", "system-dump"}:
        return ResolvedEngine("missing", None, "Modo dump solicitado, mas nenhum cliente dump está instalado.")

    return ResolvedEngine("python", None, "Nenhum cliente dump disponível; usando engine Python.")
