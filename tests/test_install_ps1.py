from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = ROOT / "install.ps1"


def test_install_ps1_persists_user_bin_in_user_path_once():
    content = INSTALL_PS1.read_text(encoding="utf-8")

    assert "[Environment]::GetEnvironmentVariable(\"Path\", \"User\")" in content
    assert "[Environment]::SetEnvironmentVariable(\"Path\", $newUserPath, \"User\")" in content
    assert "$currentUserPathParts -notcontains $UserBin" in content


def test_install_ps1_keeps_current_session_path_for_immediate_use():
    content = INSTALL_PS1.read_text(encoding="utf-8")

    assert "$currentProcessPathParts -notcontains $UserBin" in content
    assert '$env:Path = "$UserBin;$env:Path"' in content
