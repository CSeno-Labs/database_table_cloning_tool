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


def test_update_on_windows_starts_detached_updater(monkeypatch, tmp_path: Path, capsys):
    popen_calls = []
    monkeypatch.setattr("syncdb.cli.is_windows", lambda: True)
    monkeypatch.setattr("syncdb.cli.shutil.which", lambda name: "C:/Users/Neto/.local/bin/uv.exe" if name == "uv" else None)
    monkeypatch.setattr("syncdb.cli.tempfile.gettempdir", lambda: str(tmp_path))

    def fake_popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return type("Proc", (), {})()

    monkeypatch.setattr("syncdb.cli.subprocess.Popen", fake_popen)

    code = main(["update"])

    assert code == 0
    assert popen_calls
    command, kwargs = popen_calls[0]
    assert command[:4] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    assert "CREATE_NEW_CONSOLE" not in kwargs or isinstance(kwargs["creationflags"], int)
    script = tmp_path / "sync-db-update.ps1"
    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "Start-Sleep -Seconds 2" in content
    assert "uv.exe" in content
    assert "git+https://github.com/CSeno-Labs/database_table_cloning_tool.git@main" in content
    shown = capsys.readouterr().out
    assert "janela separada" in shown


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
