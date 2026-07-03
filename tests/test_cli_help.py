from syncdb.cli import build_parser


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
