from __future__ import annotations


class FakeCursor:
    def __init__(self, create_sql: str | None = None, fail_sql: str | None = None):
        self.create_sql = create_sql
        self.fail_sql = fail_sql
        self.executed: list[str] = []
        self.closed = False

    def execute(self, sql: str) -> None:
        self.executed.append(sql)
        if sql == self.fail_sql:
            raise RuntimeError("database rejected statement")

    def fetchone(self):
        return ("orders", self.create_sql) if self.create_sql else None

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self.cursor_instance = cursor
        self.closed = False
        self.committed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def test_recreate_table_keeps_dated_backup_after_atomic_swap():
    from syncdb.schema import execute_recreate_table

    source_cursor = FakeCursor("CREATE TABLE `orders` (`id` INT NOT NULL, PRIMARY KEY (`id`)) ENGINE=InnoDB")
    destination_cursor = FakeCursor()
    source = FakeConnection(source_cursor)
    destination = FakeConnection(destination_cursor)

    report = execute_recreate_table(
        {"connection": source},
        {"connection": destination},
        "orders",
        keep_backup=True,
        temporary_name="orders_syncdb_recreate_tmp_abc123",
        backup_name="orders_syncdb_backup_20260824_120000",
    )

    assert report.ok is True
    assert report.backup_table == "orders_syncdb_backup_20260824_120000"
    assert source_cursor.executed == ["SHOW CREATE TABLE `orders`"]
    assert destination_cursor.executed == [
        "CREATE TABLE `orders_syncdb_recreate_tmp_abc123` (`id` INT NOT NULL, PRIMARY KEY (`id`)) ENGINE=InnoDB",
        "RENAME TABLE `orders` TO `orders_syncdb_backup_20260824_120000`, `orders_syncdb_recreate_tmp_abc123` TO `orders`",
    ]
    assert destination.committed is True


def test_recreate_table_drops_old_table_only_after_atomic_swap():
    from syncdb.schema import execute_recreate_table

    source_cursor = FakeCursor("CREATE TABLE `orders` (`id` INT)")
    destination_cursor = FakeCursor()
    destination = FakeConnection(destination_cursor)

    report = execute_recreate_table(
        {"connection": FakeConnection(source_cursor)},
        {"connection": destination},
        "orders",
        keep_backup=False,
        temporary_name="orders_syncdb_recreate_tmp_abc123",
        backup_name="orders_syncdb_backup_20260824_120000",
    )

    assert report.ok is True
    assert report.backup_table is None
    assert destination_cursor.executed == [
        "CREATE TABLE `orders_syncdb_recreate_tmp_abc123` (`id` INT)",
        "RENAME TABLE `orders` TO `orders_syncdb_backup_20260824_120000`, `orders_syncdb_recreate_tmp_abc123` TO `orders`",
        "DROP TABLE `orders_syncdb_backup_20260824_120000`",
    ]
    assert destination.committed is True


def test_recreate_table_reports_retained_old_table_when_drop_after_swap_fails():
    from syncdb.schema import execute_recreate_table

    backup = "orders_syncdb_backup_20260824_120000"
    drop_sql = f"DROP TABLE `{backup}`"
    source_cursor = FakeCursor("CREATE TABLE `orders` (`id` INT)")
    destination_cursor = FakeCursor(fail_sql=drop_sql)

    report = execute_recreate_table(
        {"connection": FakeConnection(source_cursor)},
        {"connection": FakeConnection(destination_cursor)},
        "orders",
        keep_backup=False,
        temporary_name="orders_syncdb_recreate_tmp_abc123",
        backup_name=backup,
    )

    assert report.ok is False
    assert report.failed == drop_sql
    assert report.backup_table == backup
    assert destination_cursor.executed[-1] == drop_sql


def test_recreate_table_rewrites_only_the_leading_create_table_identifier():
    from syncdb.schema import rewrite_create_table_identifier

    source_sql = "CREATE TABLE IF NOT EXISTS `orders` (`note` VARCHAR(30) DEFAULT 'CREATE TABLE `orders`')"

    assert rewrite_create_table_identifier(source_sql, "orders_tmp") == (
        "CREATE TABLE IF NOT EXISTS `orders_tmp` (`note` VARCHAR(30) DEFAULT 'CREATE TABLE `orders`')"
    )
