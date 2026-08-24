import re

from syncdb.schema import SchemaSnapshot, build_schema_plan, compare_schema


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

    assert diff.reordered_columns == ("nome",)


def test_column_move_plan_converges_to_source_order_in_one_run():
    source = snapshot(
        "pessoa",
        (
            ("id", "int", "NO", None, "", None, 1),
            ("nome", "varchar(150)", "NO", None, "", None, 2),
            ("email", "varchar(150)", "NO", None, "", None, 3),
            ("ativo", "tinyint", "NO", None, "", None, 4),
        ),
    )
    target = snapshot(
        "pessoa",
        (
            ("email", "varchar(150)", "NO", None, "", None, 1),
            ("ativo", "tinyint", "NO", None, "", None, 2),
            ("id", "int", "NO", None, "", None, 3),
            ("nome", "varchar(150)", "NO", None, "", None, 4),
        ),
    )

    plan = build_schema_plan(compare_schema(source, target), action="copy", source=source, target=target)
    order = [column[0] for column in target.columns]
    for operation in (item for item in plan.operations if item.action == "move"):
        order.remove(operation.name)
        after = re.search(r" AFTER `([^`]+)`;", operation.sql)
        if after:
            order.insert(order.index(after.group(1)) + 1, operation.name)
        else:
            assert operation.sql.endswith(" FIRST;")
            order.insert(0, operation.name)

    assert order == [column[0] for column in source.columns]
