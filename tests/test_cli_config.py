from pathlib import Path

from syncdb.cli import choose_editor, main


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


def test_choose_editor_accepts_real_editor_env(monkeypatch):
    monkeypatch.setenv("EDITOR", "code")

    assert choose_editor(os_name="nt") == "code"
