import threading

from syncdb.schema import SchemaSnapshot, compare_schema, inspect_schema_pair


def snapshot(columns):
    return SchemaSnapshot(table="pessoa", exists=True, columns=tuple(columns))


def test_compare_schema_explains_which_column_attributes_changed():
    source = snapshot((("nome", "varchar(150)", "NO", None, "", "utf8mb4_unicode_ci", 1),))
    target = snapshot((("nome", "varchar(80)", "YES", "", "", "latin1_swedish_ci", 1),))

    diff = compare_schema(source, target)

    assert diff.column_changes == (("nome", ("type", "nullable", "default", "collation")),)


def test_inspect_schema_pair_reads_origin_and_destination_concurrently(monkeypatch):
    both_started = threading.Event()
    calls = []

    def fake_inspect(profile, table):
        calls.append(profile["alias"])
        if len(calls) == 2:
            both_started.set()
        assert both_started.wait(timeout=0.2), "schema inspections ran serially"
        return SchemaSnapshot(table=table, exists=True)

    monkeypatch.setattr("syncdb.schema.inspect_schema", fake_inspect)

    source, target = inspect_schema_pair({"alias": "prod"}, {"alias": "homolog"}, "pessoa")

    assert source.exists is True
    assert target.exists is True
    assert sorted(calls) == ["homolog", "prod"]
