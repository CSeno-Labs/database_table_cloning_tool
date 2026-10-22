import json
from pathlib import Path

from syncdb.cli import main
from syncdb.paths import AppPaths

EXE_PATH = "C:/fake/local/bin/sync-db.exe"


def test_version_flag_reports_3_0_3(capsys):
    code = main(["--version"])

    assert code == 0
    assert "sync-db 3.0.3" in capsys.readouterr().out


def test_short_version_flag_reports_3_0_3(capsys):
    code = main(["-v"])

    assert code == 0
    assert "sync-db 3.0.3" in capsys.readouterr().out


def test_interactive_startup_notifies_about_cached_update(monkeypatch, tmp_path: Path, capsys):
    paths = AppPaths.from_base(tmp_path)
    paths.ensure_dirs()
    paths.config_file.write_text(json.dumps({"language": "en", "profiles": {}}), encoding="utf-8")
    monkeypatch.setattr("syncdb.cli.run_interactive_menu", lambda _paths: 0)
    monkeypatch.setattr("syncdb.cli.check_for_update", lambda *_args: "3.0.3", raising=False)

    assert main(["--config", str(paths.config_file)]) == 0

    output = capsys.readouterr().out
    assert "Update available: 3.0.3" in output
    assert "sync-db update" in output


def test_interactive_startup_update_notice_uses_configured_portuguese(monkeypatch, tmp_path: Path, capsys):
    paths = AppPaths.from_base(tmp_path)
    paths.ensure_dirs()
    paths.config_file.write_text(json.dumps({"language": "pt-BR", "profiles": {}}), encoding="utf-8")
    monkeypatch.setattr("syncdb.cli.run_interactive_menu", lambda _paths: 0)
    monkeypatch.setattr("syncdb.cli.check_for_update", lambda *_args: "3.0.3")

    assert main(["--config", str(paths.config_file)]) == 0

    output = capsys.readouterr().out
    assert "Atualização disponível: 3.0.3" in output
    assert "Execute `sync-db update`" in output


def test_interactive_startup_holds_update_notice_until_any_key(monkeypatch, tmp_path: Path, capsys):
    paths = AppPaths.from_base(tmp_path)
    paths.ensure_dirs()
    paths.config_file.write_text(json.dumps({"language": "pt-BR", "profiles": {}}), encoding="utf-8")
    events: list[str] = []

    class TTY:
        @staticmethod
        def isatty() -> bool:
            return True

    def read_key() -> str:
        events.append("key")
        return "x"

    def run_menu(_paths: AppPaths) -> int:
        events.append("menu")
        return 0

    monkeypatch.setattr("syncdb.cli.sys.stdin", TTY())
    monkeypatch.setattr("syncdb.cli.read_key", read_key, raising=False)
    monkeypatch.setattr("syncdb.cli.run_interactive_menu", run_menu)
    monkeypatch.setattr("syncdb.cli.check_for_update", lambda *_args: "3.0.3")

    assert main(["--config", str(paths.config_file)]) == 0

    output = capsys.readouterr().out
    assert "Atualização disponível: 3.0.3" in output
    assert "Pressione qualquer tecla para continuar" in output
    assert events == ["key", "menu"]


def test_version_flag_does_not_run_update_check(monkeypatch, capsys):
    def unexpected_check(*_args):
        raise AssertionError("update check should only run for the interactive menu")

    monkeypatch.setattr("syncdb.cli.check_for_update", unexpected_check)

    assert main(["--version"]) == 0
    assert "sync-db 3.0.3" in capsys.readouterr().out


def test_update_reinstalls_from_main_with_uv(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("syncdb.cli.shutil.which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    def fake_run(command, text, capture_output, check):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "updated", "stderr": ""})()

    monkeypatch.setattr("syncdb.cli.subprocess.run", fake_run)

    code = main(["update"])

    assert code == 0
    assert calls == [["/usr/bin/uv", "tool", "install", "--reinstall", "git+https://github.com/CSeno-Labs/database_table_cloning_tool.git@main"]]
    shown = capsys.readouterr().out
    assert "Atualizando sync-db a partir da main" in shown
    assert "Atualização concluída" in shown


def test_update_on_windows_renames_running_exe_before_reinstall(monkeypatch, tmp_path: Path, capsys):
    """Windows: rename the running .exe (found via shutil.which) so uv can overwrite it."""
    monkeypatch.setattr("syncdb.cli.is_windows", lambda: True)

    def fake_which(name: str) -> str | None:
        if name == "uv":
            return "C:/Users/Neto/.local/bin/uv.exe"
        if name in ("sync-db", "sync-db.exe"):
            return EXE_PATH
        return None

    monkeypatch.setattr("syncdb.cli.shutil.which", fake_which)
    monkeypatch.setattr("syncdb.cli.os.path.isfile", lambda p: p == EXE_PATH)
    monkeypatch.setattr("syncdb.cli.os.path.exists", lambda p: False)

    renames: list = []
    removes: list = []
    monkeypatch.setattr("syncdb.cli.os.rename", lambda src, dst: renames.append((src, dst)))
    monkeypatch.setattr("syncdb.cli.os.remove", lambda path: removes.append(path))

    run_calls = []
    def fake_run(command, text, capture_output, check):
        run_calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "updated", "stderr": ""})()

    monkeypatch.setattr("syncdb.cli.subprocess.run", fake_run)

    code = main(["update"])

    assert code == 0
    assert renames == [(EXE_PATH, EXE_PATH + ".old")]
    assert run_calls == [["C:/Users/Neto/.local/bin/uv.exe", "tool", "install", "--reinstall", "git+https://github.com/CSeno-Labs/database_table_cloning_tool.git@main"]]
    assert removes == [EXE_PATH + ".old"]
    shown = capsys.readouterr().out
    assert "janela separada" not in shown
    assert "Atualizando sync-db" in shown


def test_update_on_windows_removes_stale_old_before_rename(monkeypatch, tmp_path: Path, capsys):
    """Windows: if a .old file already exists from a previous update, remove it first."""
    monkeypatch.setattr("syncdb.cli.is_windows", lambda: True)

    def fake_which(name: str) -> str | None:
        if name == "uv":
            return "C:/Users/Neto/.local/bin/uv.exe"
        if name in ("sync-db", "sync-db.exe"):
            return EXE_PATH
        return None

    monkeypatch.setattr("syncdb.cli.shutil.which", fake_which)
    monkeypatch.setattr("syncdb.cli.os.path.isfile", lambda p: p == EXE_PATH)
    monkeypatch.setattr("syncdb.cli.os.path.exists", lambda p: p == EXE_PATH + ".old")

    removes: list = []
    renames: list = []
    monkeypatch.setattr("syncdb.cli.os.rename", lambda src, dst: renames.append((src, dst)))
    monkeypatch.setattr("syncdb.cli.os.remove", lambda path: removes.append(path))
    monkeypatch.setattr(
        "syncdb.cli.subprocess.run",
        lambda command, text, capture_output, check: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    code = main(["update"])

    assert code == 0
    assert removes[0] == EXE_PATH + ".old"
    assert renames == [(EXE_PATH, EXE_PATH + ".old")]


def test_update_on_windows_restores_exe_when_uv_fails(monkeypatch, tmp_path: Path, capsys):
    """Windows: if uv fails after the rename, restore .old back to .exe."""
    monkeypatch.setattr("syncdb.cli.is_windows", lambda: True)

    def fake_which(name: str) -> str | None:
        if name == "uv":
            return "C:/Users/Neto/.local/bin/uv.exe"
        if name in ("sync-db", "sync-db.exe"):
            return EXE_PATH
        return None

    monkeypatch.setattr("syncdb.cli.shutil.which", fake_which)
    monkeypatch.setattr("syncdb.cli.os.path.isfile", lambda p: p == EXE_PATH)
    monkeypatch.setattr("syncdb.cli.os.path.exists", lambda p: False)

    renames: list = []
    monkeypatch.setattr("syncdb.cli.os.rename", lambda src, dst: renames.append((src, dst)))
    monkeypatch.setattr("syncdb.cli.os.remove", lambda path: None)
    monkeypatch.setattr(
        "syncdb.cli.subprocess.run",
        lambda command, text, capture_output, check: type("R", (), {"returncode": 1, "stdout": "", "stderr": "install failed"})(),
    )

    code = main(["update"])

    assert code == 1
    assert (EXE_PATH, EXE_PATH + ".old") in renames
    assert (EXE_PATH + ".old", EXE_PATH) in renames


def test_update_reports_missing_uv(monkeypatch, capsys):
    monkeypatch.setattr("syncdb.cli.shutil.which", lambda name: None)

    code = main(["update"])

    assert code == 1
    shown = capsys.readouterr().out
    assert "uv não encontrado" in shown


def test_init_quiet_suppresses_setup_messages(tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"

    code = main(["--config", str(config), "init", "--quiet"])

    assert code == 0
    assert config.exists()
    assert capsys.readouterr().out == ""


def test_keyboard_interrupt_is_handled_cleanly(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"

    def raise_interrupt(paths):
        raise KeyboardInterrupt

    monkeypatch.setattr("syncdb.cli.run_interactive_menu", raise_interrupt)

    code = main(["--config", str(config)])

    assert code == 130
    shown = capsys.readouterr().out
    assert "sync-db" in shown
    assert "by: SNeto99" in shown
    assert "Traceback" not in shown
