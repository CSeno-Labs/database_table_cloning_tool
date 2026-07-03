from syncdb.managed_client import detect_platform, select_release_file


def test_detect_platform_windows_x64():
    assert detect_platform(system="Windows", machine="AMD64") == ("Windows", "x86_64", "winx64.zip")


def test_detect_platform_linux_x64():
    assert detect_platform(system="Linux", machine="x86_64") == ("Linux", "x86_64", "linux-systemd-x86_64.tar.gz")


def test_select_release_file_picks_non_debug_windows_zip():
    release = {
        "release_data": {
            "11.4.8": {
                "files": [
                    {
                        "file_name": "mariadb-11.4.8-winx64-debugsymbols.zip",
                        "os": "Windows",
                        "cpu": "x86_64",
                        "file_download_url": "https://example/debug.zip",
                        "checksum": {"sha256sum": "bad"},
                    },
                    {
                        "file_name": "mariadb-11.4.8-winx64.zip",
                        "os": "Windows",
                        "cpu": "x86_64",
                        "file_download_url": "http://example/mariadb.zip",
                        "checksum": {"sha256sum": "abc"},
                    },
                ]
            }
        }
    }

    package = select_release_file(release, os_name="Windows", cpu="x86_64", filename_suffix="winx64.zip")

    assert package.file_name == "mariadb-11.4.8-winx64.zip"
    assert package.url == "https://example/mariadb.zip"
    assert package.sha256 == "abc"


def test_select_release_file_picks_linux_tarball():
    release = {
        "release_data": {
            "11.4.8": {
                "files": [
                    {
                        "file_name": "mariadb-11.4.8-linux-systemd-x86_64.tar.gz",
                        "os": "Linux",
                        "cpu": "x86_64",
                        "file_download_url": "http://example/mariadb.tar.gz",
                        "checksum": {"sha256sum": "def"},
                    }
                ]
            }
        }
    }

    package = select_release_file(release, os_name="Linux", cpu="x86_64", filename_suffix="linux-systemd-x86_64.tar.gz")

    assert package.file_name.endswith(".tar.gz")
    assert package.url == "https://example/mariadb.tar.gz"
