from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen, urlretrieve

from .clients import DumpClient, find_managed_client
from .paths import AppPaths

DEFAULT_MARIADB_VERSION = "11.4.8"
MARIADB_REST_BASE = "https://downloads.mariadb.org/rest-api/mariadb"


class ManagedClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClientPackage:
    version: str
    file_name: str
    url: str
    sha256: str
    os_name: str
    cpu: str


def detect_platform(system: str | None = None, machine: str | None = None) -> tuple[str, str, str]:
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    machine_aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
    }
    cpu = machine_aliases.get(machine, machine)

    if system == "Windows" and cpu == "x86_64":
        return "Windows", cpu, "winx64.zip"
    if system == "Linux" and cpu == "x86_64":
        return "Linux", cpu, "linux-systemd-x86_64.tar.gz"
    raise ManagedClientError(
        f"Cliente MariaDB gerenciado ainda não tem pacote automático para {system}/{machine}. "
        "Use cliente do sistema ou fallback Python."
    )


def release_api_url(version: str = DEFAULT_MARIADB_VERSION) -> str:
    return f"{MARIADB_REST_BASE}/{version}/"


def fetch_release_data(version: str = DEFAULT_MARIADB_VERSION) -> dict:
    with urlopen(release_api_url(version), timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_default_package(version: str = DEFAULT_MARIADB_VERSION) -> ClientPackage:
    os_name, cpu, suffix = detect_platform()
    data = fetch_release_data(version)
    return select_release_file(data, os_name=os_name, cpu=cpu, filename_suffix=suffix)


def select_release_file(release_data: dict, *, os_name: str, cpu: str, filename_suffix: str) -> ClientPackage:
    releases = release_data.get("release_data") or {}
    if not releases:
        raise ManagedClientError("Resposta da API MariaDB não contém release_data.")
    version, release = next(iter(releases.items()))
    for file_info in release.get("files", []):
        file_name = file_info.get("file_name") or ""
        lower = file_name.lower()
        if "debug" in lower:
            continue
        if file_info.get("os") != os_name:
            continue
        if file_info.get("cpu") != cpu:
            continue
        if not lower.endswith(filename_suffix.lower()):
            continue
        checksum = file_info.get("checksum") or {}
        sha256 = checksum.get("sha256sum")
        url = file_info.get("file_download_url")
        if not sha256 or not url:
            continue
        return ClientPackage(
            version=version,
            file_name=file_name,
            url=url.replace("http://", "https://", 1),
            sha256=sha256,
            os_name=os_name,
            cpu=cpu,
        )
    raise ManagedClientError(f"Nenhum pacote MariaDB compatível encontrado para {os_name}/{cpu}.")


def install_managed_client(paths: AppPaths, package: ClientPackage | None = None, archive_url: str | None = None, sha256: str | None = None) -> DumpClient:
    paths.ensure_dirs()
    if archive_url:
        file_name = Path(archive_url).name or "mariadb-client.archive"
        package = ClientPackage("custom", file_name, archive_url, sha256 or "", platform.system(), platform.machine())
    else:
        package = package or resolve_default_package()

    archive = paths.cache_dir / package.file_name
    urlretrieve(package.url, archive)
    if package.sha256:
        verify_sha256(archive, package.sha256)

    target = paths.managed_client_dir / "mariadb" / "current"
    staging = paths.managed_client_dir / "mariadb" / ".staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    extract_archive(archive, staging)
    flatten_single_root(staging)
    ensure_executable_bits(staging)
    validate_extracted_client(staging)

    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    client = find_managed_client(paths, "mariadb")
    if not client:
        raise ManagedClientError(f"Cliente extraído em {target}, mas não encontrei mariadb/mariadb-dump em bin/.")
    return client


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    if actual != expected.lower():
        raise ManagedClientError(f"Checksum SHA256 inválido para {path.name}: esperado {expected}, obtido {actual}.")


def extract_archive(archive: Path, target: Path) -> None:
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
        return
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(archive) as tf:
            safe_extract_tar(tf, target)
        return
    raise ManagedClientError(f"Formato de pacote não suportado: {archive.name}")


def safe_extract_tar(tf: tarfile.TarFile, target: Path) -> None:
    target_resolved = target.resolve()
    for member in tf.getmembers():
        member_path = (target / member.name).resolve()
        if target_resolved not in member_path.parents and member_path != target_resolved:
            raise ManagedClientError(f"Pacote tar contém caminho inseguro: {member.name}")
    tf.extractall(target)


def flatten_single_root(path: Path) -> None:
    entries = [entry for entry in path.iterdir()]
    if len(entries) != 1 or not entries[0].is_dir():
        return
    root = entries[0]
    tmp = path.parent / f"{path.name}.flat"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    for child in root.iterdir():
        shutil.move(str(child), tmp / child.name)
    shutil.rmtree(path)
    tmp.rename(path)


def ensure_executable_bits(path: Path) -> None:
    if os.name == "nt":
        return
    for candidate in list(path.glob("bin/mariadb*")) + list(path.glob("bin/mysql*")):
        if candidate.is_file():
            candidate.chmod(candidate.stat().st_mode | 0o755)


def validate_extracted_client(path: Path) -> None:
    bin_dir = path / "bin"
    if os.name == "nt":
        candidates = [bin_dir / "mariadb.exe", bin_dir / "mariadb-dump.exe"]
    else:
        candidates = [bin_dir / "mariadb", bin_dir / "mariadb-dump"]
    missing = [str(p) for p in candidates if not p.exists()]
    if missing:
        raise ManagedClientError("Pacote não contém os binários esperados: " + ", ".join(missing))
