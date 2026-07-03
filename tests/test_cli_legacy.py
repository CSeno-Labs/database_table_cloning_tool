from pathlib import Path

from syncdb.cli import main


def test_legacy_tables_option_syncs_without_subcommand(monkeypatch, tmp_path: Path, capsys):
    config = tmp_path / "config" / "config.json"
    calls = []

    def fake_run_python_sync(cfg, table):
        calls.append(table)
        from syncdb.engine import TableResult

        return TableResult(table=table, ok=True, engine="python", rows=1)

    monkeypatch.setattr("syncdb.cli.run_python_sync", fake_run_python_sync)

    code = main(["--config", str(config), "-t", "periodo", "aluno", "--mode", "python"])

    captured = capsys.readouterr()
    assert code == 0
    assert calls == ["periodo", "aluno"]
    assert "Motor:" in captured.out


def test_legacy_showtables_option_lists_tables(capsys):
    code = main(["-s", "-t", "periodo,aluno"])

    captured = capsys.readouterr()
    assert code == 0
    assert "1. periodo" in captured.out
    assert "2. aluno" in captured.out


def test_tables_without_input_explains_usage(capsys):
    code = main(["tables"])

    captured = capsys.readouterr()
    assert code == 2
    assert "Nenhuma tabela informada" in captured.out
