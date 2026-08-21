from syncdb.schema import SchemaSnapshot, compare_schema


def snapshot(table, columns):
    return SchemaSnapshot(table=table, exists=True, columns=tuple(columns))


def test_compare_schema_reports_column_order_separately_from_definition_change():
    source = snapshot(
        "pessoa",
        (
            ("id", "int", "NO", None, "auto_increment", None, 1),
            ("campo_novo", "varchar(20)", "YES", None, "", "utf8mb4_unicode_ci", 2),
            ("nome", "varchar(150)", "NO", None, "", "utf8mb4_unicode_ci", 3),
        ),
    )
    target = snapshot(
        "pessoa",
        (
            ("id", "int", "NO", None, "auto_increment", None, 1),
            ("nome", "varchar(150)", "NO", None, "", "utf8mb4_unicode_ci", 2),
        ),
    )

    diff = compare_schema(source, target)

    assert diff.missing_columns == ("campo_novo",)
    assert diff.changed_columns == ()
    assert diff.reordered_columns == ()


def test_compare_schema_still_reports_real_column_definition_change():
    source = snapshot("pessoa", (("nome", "varchar(150)", "NO", None, "", "utf8mb4_unicode_ci", 1),))
    target = snapshot("pessoa", (("nome", "varchar(80)", "YES", None, "", "utf8mb4_unicode_ci", 1),))

    diff = compare_schema(source, target)

    assert diff.changed_columns == ("nome",)
    assert diff.reordered_columns == ()


def test_compare_schema_reports_only_real_relative_order_changes():
    source = snapshot(
        "pessoa",
        (
            ("id", "int", "NO", None, "", None, 1),
            ("nome", "varchar(150)", "NO", None, "", None, 2),
            ("email", "varchar(150)", "NO", None, "", None, 3),
        ),
    )
    target = snapshot(
        "pessoa",
        (
            ("id", "int", "NO", None, "", None, 1),
            ("email", "varchar(150)", "NO", None, "", None, 2),
            ("nome", "varchar(150)", "NO", None, "", None, 3),
        ),
    )

    diff = compare_schema(source, target)

    assert diff.reordered_columns == ("email",)
