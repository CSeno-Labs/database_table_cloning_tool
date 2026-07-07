import json
from pathlib import Path

from syncdb.cli import main
from syncdb.engine import TableResult


def test_sync_writes_log_file_for_failed_run(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"

    def fake_run_python_sync(sync_config, table):
        return TableResult(table=table, ok=False, engine="python", message="can't connect")

    monkeypatch.setattr("syncdb.cli.run_python_sync", fake_run_python_sync)

    code = main(["--config", str(config), "sync", "-t", "periodo", "--mode", "python"])

    assert code == 1
    log_file = tmp_path / "state" / "logs" / "sync-db.log"
    assert log_file.exists()
    entry = json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["origin"] == "prod"
    assert entry["destination"] == "local"
    assert entry["tables"] == ["periodo"]
    assert entry["status"] == "failed"
    assert entry["results"][0]["message"] == "can't connect"


def test_logs_tail_prints_recent_log_lines(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    log_file = tmp_path / "state" / "logs" / "sync-db.log"
    log_file.parent.mkdir(parents=True)
    log_file.write_text('{"status":"failed"}\n', encoding="utf-8")

    code = main(["--config", str(config), "logs", "tail"])

    assert code == 0
    assert '"failed"' in capsys.readouterr().out
