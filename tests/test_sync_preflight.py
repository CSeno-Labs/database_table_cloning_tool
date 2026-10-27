from types import SimpleNamespace

import pytest

from syncdb.cli import main, interactive_sync, read_table_selection_input
from syncdb.engine import TableResult


def test_interactive_table_input_resolves_quoted_like_pattern(monkeypatch, capsys):
    pattern = "frequenciaBioV2" + chr(92) + "_%"
    raw_input = "--like " + chr(34) + pattern + chr(34)
    monkeypatch.setattr("syncdb.cli.read_text_or_back", lambda prompt: raw_input)
    monkeypatch.setattr(
        "syncdb.cli.list_table_names",
        lambda profile, **kwargs: ["frequenciaBioV2_registros", "frequenciaBioV2_usuarios", "other"],
    )

    tables = read_table_selection_input({"host": "mock"})

    assert tables == ["frequenciaBioV2_registros", "frequenciaBioV2_usuarios"]
    assert "frequenciaBioV2_usuarios" in capsys.readouterr().out


def test_interactive_sync_does_not_repeat_pattern_matches_in_summary_or_confirmation(monkeypatch, tmp_path, capsys):
    from syncdb.paths import AppPaths

    config = {
        "language": "pt-BR",
        "profiles": {"local": {"host": "source"}, "localhost": {"host": "destination"}},
        "defaults": {"origin": "local", "destination": "localhost"},
    }
    pattern = "frequenciaBioV2" + chr(92) + "_*"
    tables = ["frequenciaBioV2_registros", "frequenciaBioV2_usuarios"]
    monkeypatch.setattr("syncdb.cli.load_config", lambda paths: config)
    monkeypatch.setattr("syncdb.cli.read_last_tables", lambda paths, config: [])
    choices = iter(["local", "localhost"])
    monkeypatch.setattr("syncdb.cli.choose_profile", lambda *args, **kwargs: next(choices))
    monkeypatch.setattr("syncdb.cli.read_text_or_back", lambda prompt: "--like " + chr(34) + pattern + chr(34))
    monkeypatch.setattr("syncdb.cli.list_table_names", lambda profile, **kwargs: tables)
    monkeypatch.setattr("syncdb.cli.confirm", lambda prompt: True)
    monkeypatch.setattr("syncdb.cli.cmd_sync", lambda *args, **kwargs: 0)

    assert interactive_sync(AppPaths.from_base(tmp_path)) == 0
    output = capsys.readouterr().out

    assert output.count(tables[0]) == 1
    assert output.count(tables[1]) == 1
    assert "Selected tables:" not in output
    assert "local → localhost" in output
    assert "--like" in output and "%" in output and "_" in output and "*" in output
    assert "Tip:" in output or "Dica:" in output


def test_sync_like_lists_source_matches_and_requires_confirmation(monkeypatch, tmp_path, capsys):
    config = tmp_path / "config" / "config.json"
    pattern = "frequenciaBioV2" + chr(92) + "_%"
    source_tables = ["frequenciaBioV2_registros", "frequenciaBioV2_usuarios", "outra"]
    attempted_tables = []
    confirmations = []

    monkeypatch.setattr("syncdb.cli.list_table_names", lambda profile, **kwargs: source_tables)
    monkeypatch.setattr("syncdb.cli.test_connection", lambda *args, **kwargs: (True, "server version"))
    monkeypatch.setattr("syncdb.cli.resolve_client", lambda *args: SimpleNamespace(kind="python", reason="test", client=None))
    monkeypatch.setattr("syncdb.cli.confirm", lambda prompt: confirmations.append(prompt) or True)
    monkeypatch.setattr("syncdb.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "syncdb.cli.run_python_sync",
        lambda _config, table: attempted_tables.append(table) or TableResult(table=table, ok=True, engine="python", rows=1),
    )

    code = main(["--config", str(config), "sync", "--like", pattern, "--mode", "python"])

    assert code == 0
    assert attempted_tables == source_tables[:2]
    assert len(confirmations) == 1
    output = capsys.readouterr().out
    assert "frequenciaBioV2_registros" in output
    assert "frequenciaBioV2_usuarios" in output
    assert "outra" not in output


def test_sync_like_without_matches_stops_before_preflight_or_sync(monkeypatch, tmp_path, capsys):
    config = tmp_path / "config" / "config.json"
    monkeypatch.setattr("syncdb.cli.list_table_names", lambda profile, **kwargs: ["unrelated"])
    monkeypatch.setattr("syncdb.cli.test_connection", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not preflight when no tables match")))

    code = main(["--config", str(config), "sync", "--like", "missing_%", "--mode", "python"])

    assert code == 2
    assert "Nenhuma tabela da origem corresponde" in capsys.readouterr().out


def test_sync_like_requires_yes_confirmation_without_interactive_terminal(monkeypatch, tmp_path, capsys):
    config = tmp_path / "config" / "config.json"
    monkeypatch.setattr("syncdb.cli.list_table_names", lambda profile, **kwargs: ["table_one"])
    monkeypatch.setattr("syncdb.cli.sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("syncdb.cli.test_connection", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not preflight before confirmation")))

    code = main(["--config", str(config), "sync", "--like", "table_%", "--mode", "python"])

    assert code == 2
    assert "use --yes" in capsys.readouterr().out


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
