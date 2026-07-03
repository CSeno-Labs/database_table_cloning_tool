from pathlib import Path

from syncdb.cli import choose_editor, main, open_editor


def test_doctor_reports_invalid_json_without_traceback(tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"destino": {"password": "abc\ndef"}}', encoding="utf-8")

    code = main(["--config", str(config), "doctor"])

    captured = capsys.readouterr()
    assert code == 2
    assert "Config JSON inválido" in captured.out
    assert "line 1 column" in captured.out
    assert "Traceback" not in captured.out


def test_choose_editor_ignores_shell_values_on_windows(monkeypatch):
    monkeypatch.setenv("EDITOR", "pwsh")

    assert choose_editor(os_name="nt") == "notepad"


def test_config_edit_on_windows_launches_editor_without_waiting(monkeypatch, tmp_path: Path):
    calls = []

    class FakeProcess:
        pass

    def fake_popen(args):
        calls.append(args)
        return FakeProcess()

    monkeypatch.setattr("syncdb.cli.subprocess.Popen", fake_popen)

    assert open_editor("notepad", tmp_path / "config.json", os_name="nt") == 0
    assert calls == [["notepad", str(tmp_path / "config.json")]]


def test_choose_editor_accepts_real_editor_env(monkeypatch):
    monkeypatch.setenv("EDITOR", "code")

    assert choose_editor(os_name="nt") == "code"
