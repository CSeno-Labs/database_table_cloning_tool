from types import SimpleNamespace

import pytest

from syncdb.cli import main
from syncdb.engine import TableResult


@pytest.mark.parametrize(
    ("failed_tag", "expected_calls"),
    [("prod", ["prod"]), ("local", ["prod", "local"])],
)
def test_sync_aborts_before_processing_tables_when_preflight_connection_fails(
    monkeypatch, tmp_path, capsys, failed_tag, expected_calls
):
    config = tmp_path / "config" / "config.json"
    checked = []
    attempted_tables = []

    def fake_test_connection(profile, *, connection_timeout=None):
        checked.append((profile["alias"], connection_timeout))
        if profile["alias"] == failed_tag:
            return False, "simulated connection failure"
        return True, "server version"

    monkeypatch.setattr("syncdb.cli.test_connection", fake_test_connection)
    monkeypatch.setattr(
        "syncdb.cli.resolve_client",
        lambda *args: SimpleNamespace(kind="dump", reason="test client", client=object()),
    )

    def fake_run_dump_sync(_config, table, _client, _paths):
        attempted_tables.append(table)
        return TableResult(table=table, ok=True, engine="dump", rows=1)

    monkeypatch.setattr("syncdb.cli.run_dump_sync", fake_run_dump_sync)

    code = main(
        [
            "--config",
            str(config),
            "sync",
            "-t",
            "first_table",
            "second_table",
            "--mode",
            "dump",
        ]
    )

    assert code == 1
    assert [tag for tag, _ in checked] == expected_calls
    assert all(timeout == 5 for _, timeout in checked)
    assert attempted_tables == []
    output = capsys.readouterr().out.lower()
    assert "preflight" in output or "pré-verificação" in output
    assert "simulated connection failure" in output


def test_sync_stops_after_source_connectivity_failure(monkeypatch, tmp_path, capsys):
    config = tmp_path / "config" / "config.json"
    attempted_tables = []

    monkeypatch.setattr("syncdb.cli.test_connection", lambda *args, **kwargs: (True, "server version"))
    monkeypatch.setattr(
        "syncdb.cli.resolve_client",
        lambda *args: SimpleNamespace(kind="dump", reason="test client", client=object()),
    )

    def fake_run_dump_sync(_config, table, _client, _paths):
        attempted_tables.append(table)
        if table == "first_table":
            return TableResult(
                table=table,
                ok=False,
                engine="dump",
                stage="dump_source",
                message="mariadb-dump: Got error: 2002: Can't connect (10060)",
                details="mariadb-dump: Got error: 2002: Can't connect (10060)",
            )
        return TableResult(table=table, ok=True, engine="dump", rows=1)

    monkeypatch.setattr("syncdb.cli.run_dump_sync", fake_run_dump_sync)

    code = main(
        [
            "--config",
            str(config),
            "sync",
            "-t",
            "first_table",
            "second_table",
            "third_table",
            "--mode",
            "dump",
        ]
    )

    assert code == 1
    assert attempted_tables == ["first_table"]
    assert "2 tabelas restantes não foram processadas" in capsys.readouterr().out
