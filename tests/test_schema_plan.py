from syncdb.schema import SchemaSnapshot, build_schema_plan, compare_schema


def snapshot(*, columns=(), indexes=(), foreign_keys=(), options=()):
    return SchemaSnapshot(
        table="pessoa",
        exists=True,
        columns=tuple(columns),
        indexes=tuple(indexes),
        foreign_keys=tuple(foreign_keys),
        table_options=tuple(options),
    )


def test_copy_plan_adds_changes_reorders_and_removes_extras():
    source = snapshot(
        columns=(
            ("id", "int", "NO", None, "", None, 1),
            ("novo", "varchar(20)", "YES", None, "", None, 2),
            ("nome", "varchar(150)", "NO", None, "", None, 3),
        ),
        indexes=(("idx_novo", False, ("novo",)),),
    )
    target = snapshot(
        columns=(
            ("id", "int", "NO", None, "", None, 1),
            ("nome", "varchar(80)", "YES", None, "", None, 2),
            ("campo_dev", "text", "YES", None, "", None, 3),
        ),
        indexes=(("idx_dev", False, ("campo_dev",)),),
    )

    plan = build_schema_plan(compare_schema(source, target), action="copy", source=source, target=target)

    assert [(item.action, item.category, item.name) for item in plan.operations] == [
        ("add", "column", "novo"),
        ("modify", "column", "nome"),
        ("drop", "column", "campo_dev"),
        ("add", "index", "idx_novo"),
        ("drop", "index", "idx_dev"),
    ]
    assert plan.operations[0].details == ("VARCHAR(20) NULL", "depois de id")
    assert plan.operations[1].details == ("destino: VARCHAR(80) NULL", "origem: VARCHAR(150) NOT NULL")
    assert plan.operations[0].sql == "ALTER TABLE `pessoa` ADD COLUMN `novo` VARCHAR(20) NULL AFTER `id`;"
    assert plan.operations[1].sql == "ALTER TABLE `pessoa` MODIFY COLUMN `nome` VARCHAR(150) NOT NULL;"


def test_update_plan_preserves_extras_but_still_adds_and_modifies():
    source = snapshot(
        columns=(("id", "int", "NO", None, "", None, 1), ("novo", "varchar(20)", "YES", None, "", None, 2)),
        indexes=(("idx_novo", False, ("novo",)),),
    )
    target = snapshot(
        columns=(("id", "int", "NO", None, "", None, 1), ("campo_dev", "text", "YES", None, "", None, 2)),
        indexes=(("idx_dev", False, ("campo_dev",)),),
    )

    plan = build_schema_plan(compare_schema(source, target), action="update", source=source, target=target)

    assert [(item.action, item.category, item.name) for item in plan.operations] == [
        ("add", "column", "novo"),
        ("preserve", "column", "campo_dev"),
        ("add", "index", "idx_novo"),
        ("preserve", "index", "idx_dev"),
    ]
    assert plan.has_destructive_operations is False


def test_plan_generates_sql_for_real_column_reordering():
    source = snapshot(columns=(("id", "int", "NO", None, "", None, 1), ("nome", "varchar(100)", "NO", None, "", None, 2), ("email", "varchar(100)", "YES", None, "", None, 3)))
    target = snapshot(columns=(("id", "int", "NO", None, "", None, 1), ("email", "varchar(100)", "YES", None, "", None, 2), ("nome", "varchar(100)", "NO", None, "", None, 3)))

    plan = build_schema_plan(compare_schema(source, target), action="copy", source=source, target=target)
    move = next(item for item in plan.operations if item.action == "move")

    assert move.name == "email"
    assert move.details == ("destino: depois de id", "origem: depois de nome")
    assert move.sql == "ALTER TABLE `pessoa` MODIFY COLUMN `email` VARCHAR(100) NULL AFTER `nome`;"
