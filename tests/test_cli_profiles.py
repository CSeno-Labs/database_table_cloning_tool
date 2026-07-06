from pathlib import Path

from syncdb.cli import main


def test_db_add_interactively_saves_profile(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    answers = iter([
        "prod_leitura",
        "Produção leitura",
        "prod.example.com",
        "3306",
        "reader",
        "secret",
        "sistema",
        "latin1",
        "s",
        "n",
        "n",
    ])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    code = main(["--config", str(config), "db", "add"])

    assert code == 0
    shown = capsys.readouterr().out
    assert "Banco salvo: prod_leitura" in shown
    assert main(["--config", str(config), "db", "list"]) == 0
    shown = capsys.readouterr().out
    assert "prod_leitura" in shown
    assert "source_only" in shown


def test_db_add_refuses_existing_tag(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    answers = iter(["local"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    code = main(["--config", str(config), "db", "add"])

    assert code == 2
    assert "já existe" in capsys.readouterr().out


def test_db_set_defaults_updates_origin_and_destination(tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    main(["--config", str(config), "init"])

    code = main(["--config", str(config), "db", "set-defaults", "-o", "prod", "-d", "local"])

    assert code == 0
    shown = capsys.readouterr().out
    assert "Origem padrão: prod" in shown
    assert "Destino padrão: local" in shown


def test_sync_uses_origin_destination_flags_and_saves_last_tables(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    calls = []

    def fake_run_python_sync(sync_config, table):
        calls.append((sync_config["origem"]["alias"], sync_config["destino"]["alias"], table))
        from syncdb.engine import TableResult

        return TableResult(table=table, ok=True, engine="python", rows=1)

    monkeypatch.setattr("syncdb.cli.run_python_sync", fake_run_python_sync)

    code = main(["--config", str(config), "sync", "-t", "periodo", "aluno", "-o", "prod", "-d", "local", "--mode", "python"])

    assert code == 0
    assert calls == [("prod", "local", "periodo"), ("prod", "local", "aluno")]
    last_file = tmp_path / "config" / "last_tables.txt"
    assert last_file.read_text(encoding="utf-8").splitlines() == ["periodo", "aluno"]


def test_sync_backup_flag_sets_runtime_config(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    seen = []

    def fake_run_python_sync(sync_config, table):
        seen.append(sync_config["sync"].get("backup_before_replace"))
        from syncdb.engine import TableResult

        return TableResult(table=table, ok=True, engine="python", rows=1, backup_table="periodo_bkp")

    dropped = []
    monkeypatch.setattr("syncdb.cli.run_python_sync", fake_run_python_sync)
    monkeypatch.setattr("syncdb.cli.drop_table", lambda config, table: dropped.append(table))

    code = main(["--config", str(config), "sync", "-t", "periodo", "--mode", "python", "--backup"])

    assert code == 0
    assert seen == [True]
    assert dropped == ["periodo_bkp"]


def test_sync_backup_keep_does_not_drop_successful_backup(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"

    def fake_run_python_sync(sync_config, table):
        from syncdb.engine import TableResult

        return TableResult(table=table, ok=True, engine="python", rows=1, backup_table="periodo_bkp")

    dropped = []
    monkeypatch.setattr("syncdb.cli.run_python_sync", fake_run_python_sync)
    monkeypatch.setattr("syncdb.cli.drop_table", lambda config, table: dropped.append(table))

    code = main(["--config", str(config), "sync", "-t", "periodo", "--mode", "python", "--backup", "keep"])

    assert code == 0
    assert dropped == []


def test_sync_without_backup_does_not_enable_backup(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    seen = []

    def fake_run_python_sync(sync_config, table):
        seen.append(sync_config["sync"].get("backup_before_replace"))
        from syncdb.engine import TableResult

        return TableResult(table=table, ok=True, engine="python", rows=1)

    monkeypatch.setattr("syncdb.cli.run_python_sync", fake_run_python_sync)

    code = main(["--config", str(config), "sync", "-t", "periodo", "--mode", "python"])

    assert code == 0
    assert seen == [False]


def test_backup_command_uses_suggested_names_with_yes(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    calls = []

    def fake_run_table_backup(db_config, table, backup_name):
        calls.append((db_config["alias"], table, backup_name))
        from syncdb.engine import TableResult

        return TableResult(table=table, ok=True, engine="backup", backup_table=backup_name)

    monkeypatch.setattr("syncdb.cli.run_table_backup", fake_run_table_backup)

    code = main(["--config", str(config), "backup", "-t", "periodo", "aluno", "-d", "local", "-y"])

    assert code == 0
    assert len(calls) == 2
    assert calls[0][0:2] == ("local", "periodo")
    assert calls[0][2].startswith("periodo_syncdb_backup_")
    assert calls[1][0:2] == ("local", "aluno")


def test_sync_where_uses_advanced_python_engine_and_yes(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    calls = []

    def fake_run_python_advanced_sync(sync_config, table, *, where_clause, insert_missing):
        calls.append((table, where_clause, insert_missing))
        from syncdb.engine import TableResult

        return TableResult(table=table, ok=True, engine="python/advanced", rows=2, sync_type="where_replace", primary_key=["id"], origin_matched_rows=2, inserted_rows=2, deleted_rows=2)

    monkeypatch.setattr("syncdb.cli.run_python_advanced_sync", fake_run_python_advanced_sync)
    monkeypatch.setattr("syncdb.cli.preflight_advanced_sync", lambda config, tables, where_clause, insert_missing: [])

    code = main(["--config", str(config), "sync", "-t", "aluno", "--where", "WHERE ano >= 2026", "-y"])

    assert code == 0
    assert calls == [("aluno", "ano >= 2026", False)]


def test_sync_where_preflight_failure_aborts_before_any_table(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    calls = []

    from syncdb.engine import TableResult

    monkeypatch.setattr("syncdb.cli.run_python_advanced_sync", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(
        "syncdb.cli.preflight_advanced_sync",
        lambda config, tables, where_clause, insert_missing: [TableResult(table="periodo", ok=False, engine="python/advanced", stage="validate_where", message="Unknown column 'idescola'")],
    )

    code = main(["--config", str(config), "sync", "-t", "aluno", "periodo", "--where", "idescola = 123", "-y"])

    assert code == 2
    assert calls == []
    shown = capsys.readouterr().out
    assert "Nenhuma tabela foi sincronizada" in shown
    assert "periodo" in shown


def test_sync_insert_missing_sets_advanced_mode(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    calls = []

    def fake_run_python_advanced_sync(sync_config, table, *, where_clause, insert_missing):
        calls.append((table, where_clause, insert_missing))
        from syncdb.engine import TableResult

        return TableResult(table=table, ok=True, engine="python/advanced", rows=1, sync_type="insert_missing", primary_key=["id"], inserted_rows=1, skipped_existing_rows=3)

    monkeypatch.setattr("syncdb.cli.run_python_advanced_sync", fake_run_python_advanced_sync)
    monkeypatch.setattr("syncdb.cli.preflight_advanced_sync", lambda config, tables, where_clause, insert_missing: [])

    code = main(["--config", str(config), "sync", "-t", "aluno", "--insert-missing", "-y"])

    assert code == 0
    assert calls == [("aluno", "", True)]


def test_sync_without_tables_no_longer_reads_default_file(tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    main(["--config", str(config), "init"])
    (tmp_path / "config" / "last_tables.txt").write_text("periodo\n", encoding="utf-8")

    code = main(["--config", str(config), "sync", "--mode", "python"])

    assert code == 2
    assert "Nenhuma tabela informada" in capsys.readouterr().out


def test_interactive_defaults_accepts_profile_numbers(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    answers = iter(["6", "1", "1", "2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    code = main(["--config", str(config)])

    assert code == 0
    shown = capsys.readouterr().out
    assert "Origem padrão: prod" in shown
    assert "Destino padrão: local" in shown


def test_interactive_sync_pauses_after_showing_result(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    answers = iter(["1", "1", "2", "periodo", "n", "s", "7"])
    prompts = []
    pauses = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)

    def fake_run_python_sync(sync_config, table):
        from syncdb.engine import TableResult

        return TableResult(table=table, ok=True, engine="python", rows=1)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr("syncdb.cli.run_python_sync", fake_run_python_sync)
    monkeypatch.setattr("syncdb.cli.pause_after_action", lambda: pauses.append(True))

    code = main(["--config", str(config)])

    assert code == 0
    assert pauses == [True]
    assert "Criar backup da tabela destino antes de sobrescrever? [s/N] (Default: Não) " in prompts


def test_interactive_backup_pauses_after_showing_result(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    answers = iter(["3", "2", "periodo", "", "7"])
    prompts = []
    pauses = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)

    def fake_run_table_backup(db_config, table, backup_name):
        from syncdb.engine import TableResult

        return TableResult(table=table, ok=True, engine="backup", backup_table=backup_name)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr("syncdb.cli.run_table_backup", fake_run_table_backup)
    monkeypatch.setattr("syncdb.cli.pause_after_action", lambda: pauses.append(True))

    code = main(["--config", str(config)])

    assert code == 0
    assert pauses == [True]


def test_db_add_charset_prompt_shows_allowed_values(monkeypatch, tmp_path: Path):
    config = tmp_path / "config" / "config.json"
    answers = iter(["novo", "Novo", "localhost", "3306", "user", "pass", "db", "", "s", "s", "n"])
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)

    assert main(["--config", str(config), "db", "add"]) == 0
    assert "Charset [latin1] (latin1, utf8): " in prompts


def test_bare_sync_db_opens_interactive_menu(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    answers = iter(["0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    code = main(["--config", str(config)])

    assert code == 0
    shown = capsys.readouterr().out
    assert "Menu sync-db" in shown
    assert "Sincronizar tabelas" in shown
