from pathlib import Path

from syncdb.cli import main

EXE_PATH = "C:/fake/local/bin/sync-db.exe"


def test_version_flag_reports_3_0_0(capsys):
    code = main(["--version"])

    assert code == 0
    assert "sync-db 3.0.0" in capsys.readouterr().out


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
