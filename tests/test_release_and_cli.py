from pathlib import Path

from syncdb.cli import main


def test_version_flag_reports_2_1_1(capsys):
    code = main(["--version"])

    assert code == 0
    assert "sync-db 2.1.1" in capsys.readouterr().out


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


def test_update_on_windows_renames_bin_exe_before_reinstall(monkeypatch, tmp_path: Path, capsys):
    """Windows: rename the bin-dir .exe (the locked one) so uv can overwrite it."""
    monkeypatch.setattr("syncdb.cli.is_windows", lambda: True)
    monkeypatch.setattr("syncdb.cli.shutil.which", lambda name: "C:/Users/Neto/.local/bin/uv.exe" if name == "uv" else None)

    # Simulate ~/.local/bin (the bin dir returned by `uv tool dir --bin`)
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    exe = bin_dir / "sync-db.exe"
    exe.write_text("old exe data", encoding="utf-8")
    monkeypatch.setattr("syncdb.cli.find_uv_bin_dir", lambda: str(bin_dir))

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
    # rename happened before uv was called
    assert renames == [(str(bin_dir / "sync-db.exe"), str(bin_dir / "sync-db.exe.old"))]
    # uv was called
    assert run_calls == [["C:/Users/Neto/.local/bin/uv.exe", "tool", "install", "--reinstall", "git+https://github.com/CSeno-Labs/database_table_cloning_tool.git@main"]]
    # .old cleanup attempted after successful reinstall
    assert removes == [str(bin_dir / "sync-db.exe.old")]
    shown = capsys.readouterr().out
    assert "janela separada" not in shown
    assert "Atualizando sync-db" in shown


def test_update_on_windows_removes_stale_old_before_rename(monkeypatch, tmp_path: Path, capsys):
    """Windows: if a .old file already exists from a previous update, remove it first."""
    monkeypatch.setattr("syncdb.cli.is_windows", lambda: True)
    monkeypatch.setattr("syncdb.cli.shutil.which", lambda name: "C:/Users/Neto/.local/bin/uv.exe" if name == "uv" else None)

    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    exe = bin_dir / "sync-db.exe"
    exe.write_text("current exe", encoding="utf-8")
    old_exe = bin_dir / "sync-db.exe.old"
    old_exe.write_text("stale old exe", encoding="utf-8")
    monkeypatch.setattr("syncdb.cli.find_uv_bin_dir", lambda: str(bin_dir))

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
    # stale .old was removed before the rename
    assert removes[0] == str(bin_dir / "sync-db.exe.old")
    assert renames == [(str(bin_dir / "sync-db.exe"), str(bin_dir / "sync-db.exe.old"))]


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
