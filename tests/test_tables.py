from pathlib import Path

from syncdb.tables import parse_tables, parse_tables_file, quote_identifier


def test_parse_tables_splits_commas_semicolons_and_newlines():
    assert parse_tables(["aluno, escola", "periodo;turma", "\nmatricula\n"]) == [
        "aluno",
        "escola",
        "periodo",
        "turma",
        "matricula",
    ]


def test_parse_tables_file_ignores_comments_and_deduplicates(tmp_path: Path):
    file = tmp_path / "tables.csv"
    file.write_text("# comentario\naluno; escola\naluno\nperiodo, turma\n", encoding="utf-8")

    assert parse_tables_file(file) == ["aluno", "escola", "periodo", "turma"]


def test_quote_identifier_rejects_suspicious_names():
    assert quote_identifier("aluno") == "`aluno`"
    assert quote_identifier("db.tabela") == "`db`.`tabela`"

    for bad in ["aluno; drop table x", "with space", "", "a`b"]:
        try:
            quote_identifier(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted suspicious identifier: {bad!r}")
