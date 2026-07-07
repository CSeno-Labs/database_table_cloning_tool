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


def test_update_on_windows_renames_exe_before_reinstall(monkeypatch, tmp_path: Path, capsys):
    """Windows: rename running .exe so uv can freely remove Scripts dir."""
    monkeypatch.setattr("syncdb.cli.is_windows", lambda: True)
    monkeypatch.setattr("syncdb.cli.shutil.which", lambda name: "C:/Users/Neto/.local/bin/uv.exe" if name == "uv" else None)

    tool_dir = tmp_path / "uv_tools" / "database-table-cloning-tool"
    scripts_dir = tool_dir / "Scripts"
    scripts_dir.mkdir(parents=True)
    exe = scripts_dir / "sync-db.exe"
    exe.write_text("old exe data", encoding="utf-8")
    monkeypatch.setattr("syncdb.cli.find_uv_tool_scripts_dir", lambda: str(scripts_dir))

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
    assert renames == [(str(scripts_dir / "sync-db.exe"), str(scripts_dir / "sync-db.exe.old"))]
    # uv was called
    assert run_calls == [["C:/Users/Neto/.local/bin/uv.exe", "tool", "install", "--reinstall", "git+https://github.com/CSeno-Labs/database_table_cloning_tool.git@main"]]
    # .old was cleaned up after successful reinstall
    assert removes == [str(scripts_dir / "sync-db.exe.old")]
    shown = capsys.readouterr().out
    assert "janela separada" not in shown
    assert "Atualizando sync-db" in shown


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
