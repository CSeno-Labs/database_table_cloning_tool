from syncdb.cli import build_parser


def test_sync_and_schema_commands_accept_like_pattern_without_tables_flag():
    parser = build_parser()

    sync_args = parser.parse_args(["sync", "--like", "frequenciaBioV2\\_%"])
    schema_args = parser.parse_args(["schema", "diff", "--like", "lotacao____"])
    short_sync_args = parser.parse_args(["sync", "-l", "frequenciaBioV2\\_%"])
    short_schema_args = parser.parse_args(["schema", "diff", "-l", "lotacao____"])

    assert sync_args.like == "frequenciaBioV2\\_%"
    assert schema_args.like == "lotacao____"
    assert short_sync_args.like == sync_args.like
    assert short_schema_args.like == schema_args.like


def test_all_table_schema_commands_accept_like():
    parser = build_parser()
    commands = [
        ["schema", "diff", "--like", "x_%"],
        ["schema", "plan", "copy", "--like", "x_%"],
        ["schema", "copy", "--like", "x_%"],
        ["schema", "update", "--like", "x_%"],
        ["schema", "recreate-table", "--like", "x_%"],
    ]

    for command in commands:
        assert parser.parse_args(command).like == "x_%"
        assert parser.parse_args([*command[:-2], "-l", "x_%"]).like == "x_%"
    assert parser.parse_args(["schema", "plan", "update", "-t", "orders", "--yes"]).yes is True


def test_sync_mode_help_lists_specific_dump_sources(capsys):
    parser = build_parser()
    try:
        parser.parse_args(["sync", "--help"])
    except SystemExit as exc:
        assert exc.code == 0

    captured = capsys.readouterr()
    assert "managed-dump" in captured.out
    assert "system-dump" in captured.out
    assert "python" in captured.out
    assert "-l PATTERN, --like PATTERN" in captured.out
