from syncdb.db import list_table_names, test_connection as check_db_connection


def test_list_table_names_reads_only_base_tables_from_current_database(monkeypatch):
    calls = []

    class Cursor:
        def execute(self, sql, params):
            calls.append((sql, params))

        def fetchall(self):
            return [("alpha",), ("beta",)]

        def close(self):
            calls.append(("cursor.close", None))

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            calls.append(("connection.close", None))

    monkeypatch.setattr("syncdb.db.get_connection", lambda config: Connection())

    assert list_table_names({"database": "source"}) == ["alpha", "beta"]
    assert calls[0][1] == ("BASE TABLE",)
    assert calls[-2:] == [("cursor.close", None), ("connection.close", None)]


def test_test_connection_passes_timeout_to_database_driver(monkeypatch):
    calls = []

    class Cursor:
        def execute(self, sql):
            calls.append(sql)

        def fetchone(self):
            return ("8.0",)

        def close(self):
            pass

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    def fake_get_connection(config, *, connection_timeout=None):
        calls.append(connection_timeout)
        return Connection()

    monkeypatch.setattr("syncdb.db.get_connection", fake_get_connection)

    assert check_db_connection({"host": "db.example"}, connection_timeout=5) == (True, "8.0")
    assert calls == [5, "SELECT VERSION()"]
