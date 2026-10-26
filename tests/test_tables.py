from pathlib import Path

from syncdb.tables import expand_table_pattern, parse_table_selection_input, parse_tables, parse_tables_file, quote_identifier, table_name_matches_pattern


def test_expand_table_pattern_returns_matching_source_names_in_catalog_order():
    available = ["frequenciaBioV2_registros", "frequenciaBioV2_usuarios", "lotacao1234"]

    pattern = "frequenciaBioV2" + chr(92) + "_%"
    assert expand_table_pattern(pattern, available) == [
        "frequenciaBioV2_registros",
        "frequenciaBioV2_usuarios",
    ]


def test_parse_table_selection_input_preserves_like_escapes_inside_quotes():
    value = "--like " + chr(34) + r"frequenciaBioV2\_%" + chr(34)
    tables, pattern = parse_table_selection_input(value)

    assert tables == []
    assert pattern == r"frequenciaBioV2\_%"


def test_parse_table_selection_input_keeps_explicit_table_list():
    assert parse_table_selection_input("alpha, beta") == (["alpha", "beta"], None)


def test_parse_table_selection_input_rejects_unclosed_like_quotes():
    import pytest

    with pytest.raises(ValueError, match="quote"):
        parse_table_selection_input('--like "pattern')


def test_table_pattern_supports_mysql_like_wildcards_and_star_alias():
    assert table_name_matches_pattern(r"frequenciaBioV2\_%", "frequenciaBioV2_registros")
    assert not table_name_matches_pattern(r"frequenciaBioV2\_%", "frequenciaBioV2Xregistros")
    assert table_name_matches_pattern("lotacao____", "lotacao1234")
    assert not table_name_matches_pattern("lotacao____", "lotacao123")
    assert table_name_matches_pattern("frequenciaBioV2_*", "frequenciaBioV2_registros")
    assert table_name_matches_pattern("literal\\%", "literal%")
    assert table_name_matches_pattern("literal\\_", "literal_")
    assert table_name_matches_pattern("literal\\*", "literal*")
    assert table_name_matches_pattern("literal\\\\", "literal\\")


def test_table_pattern_rejects_trailing_escape():
    import pytest

    with pytest.raises(ValueError, match="escape"):
        table_name_matches_pattern("prefix\\", "prefix")


def test_parse_tables_splits_commas_semicolons_newlines_and_spaces():
    assert parse_tables(["aluno, escola", "periodo;turma", "\nmatricula\n", "nota frequencia"]) == [
        "aluno",
        "escola",
        "periodo",
        "turma",
        "matricula",
        "nota",
        "frequencia",
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
