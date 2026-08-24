from syncdb.engine import ensure_structure


class FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql):
        self.executed.append(sql)


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_instance = cursor
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_python_sync_does_not_add_missing_destination_columns(monkeypatch):
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    monkeypatch.setattr("syncdb.engine.table_exists", lambda config, table: True)
    monkeypatch.setattr("syncdb.engine.get_connection", lambda config: connection)
    monkeypatch.setattr("syncdb.engine.get_columns", lambda config, table: {"id": {"Type": "INT"}})

    ensure_structure(
        {},
        "aluno",
        "CREATE TABLE `aluno` (`id` INT)",
        create_missing=True,
    )

    assert cursor.executed == []
    assert connection.committed is False
