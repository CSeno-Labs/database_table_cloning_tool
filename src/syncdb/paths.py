from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

APP_NAME = "sync-db"
APP_AUTHOR = "CSeno-Labs"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    state_dir: Path
    cache_dir: Path

    @classmethod
    def current(cls) -> "AppPaths":
        dirs = PlatformDirs(APP_NAME, APP_AUTHOR)
        return cls(
            config_dir=Path(dirs.user_config_dir),
            data_dir=Path(dirs.user_data_dir),
            state_dir=Path(dirs.user_state_dir),
            cache_dir=Path(dirs.user_cache_dir),
        )

    @classmethod
    def from_base(cls, base: Path) -> "AppPaths":
        return cls(
            config_dir=base / "config",
            data_dir=base / "data",
            state_dir=base / "state",
            cache_dir=base / "cache",
        )

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "sync-db.log"

    @property
    def managed_client_dir(self) -> Path:
        return self.data_dir / "clients"

    @property
    def temp_dir(self) -> Path:
        return self.cache_dir / "tmp"

    def ensure_dirs(self) -> None:
        for path in (self.config_dir, self.data_dir, self.state_dir, self.cache_dir, self.log_dir, self.temp_dir):
            path.mkdir(parents=True, exist_ok=True)
