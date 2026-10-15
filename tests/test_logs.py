import json
from pathlib import Path

from syncdb.cli import main
from syncdb.engine import TableResult


def test_sync_writes_log_file_for_failed_run(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"

    def fake_run_python_sync(sync_config, table):
        return TableResult(
            table=table,
            ok=False,
            engine="dump",
            stage="import_dest",
            message="Falha em import_dest de periodo: ERROR 1062 (23000) at line 14: Duplicate entry '1' for key 'PRIMARY'",
            details="full diagnostic payload",
        )

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
    assert entry["results"][0]["message"] == "Falha em import_dest de periodo: ERROR 1062 (23000) at line 14: Duplicate entry '1' for key 'PRIMARY'"
    assert entry["results"][0]["details"] == "full diagnostic payload"
    output = capsys.readouterr().out
    summary_at = output.index("Resumo")
    errors_at = output.index("Erros da sincronização")
    assert summary_at < errors_at
    assert "ERROR 1062 (23000) at line 14: Duplicate entry '1' for key 'PRIMARY'" in output[errors_at:]
    assert "Falha em import_dest de periodo" not in output[errors_at:]
    assert str(log_file) in "".join(output[errors_at:].split())
    assert "full diagnostic payload" not in output


def test_logs_tail_prints_recent_log_lines(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    log_file = tmp_path / "state" / "logs" / "sync-db.log"
    log_file.parent.mkdir(parents=True)
    log_file.write_text('{"status":"failed"}\n', encoding="utf-8")

    code = main(["--config", str(config), "logs", "tail"])

    assert code == 0
    assert '"failed"' in capsys.readouterr().out
