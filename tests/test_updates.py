"""updates.py: checking GitHub releases and fast-forwarding a git clone."""

import io
import json
import shutil
import subprocess
import sys
import urllib.error

import pytest

import updates

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def test_versions():
    assert updates.parse_version("v1.2.3") == (1, 2, 3)
    assert updates.parse_version("1.2") == (1, 2, 0)
    assert updates.parse_version("v1.2.0-rc1") is None
    assert updates.is_newer("v1.1.0", "1.0.0")
    assert not updates.is_newer("v1.0.0", "1.0.0")
    assert not updates.is_newer("nightly", "1.0.0")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_latest_release_reads_the_api():
    body = {"tag_name": "v1.2.0", "body": "Notes", "html_url": "https://example.invalid/r"}

    def opener(request, timeout):
        assert request.full_url == updates.API
        return FakeResponse(json.dumps(body).encode())

    rel = updates.latest_release("1.0.0", opener=opener)
    assert (rel.version, rel.tag, rel.notes) == ("1.2.0", "v1.2.0", "Notes")


@pytest.mark.parametrize(
    "error, message",
    [
        (urllib.error.HTTPError(updates.API, 404, "Not Found", {}, None), "No releases"),
        (urllib.error.URLError("offline"), "Couldn't reach GitHub"),
    ],
)
def test_latest_release_errors_are_readable(error, message):
    def opener(request, timeout):
        raise error

    with pytest.raises(LookupError, match=message):
        updates.latest_release("1.0.0", opener=opener)


# --- git ---------------------------------------------------------------------------


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def clone(tmp_path):
    """An 'origin' repo with v1.0.0 and v1.1.0, and a clone sitting at v1.0.0 on master."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "master")
    (origin / "pump_gui.py").write_text("v1\n")
    (origin / "requirements.txt").write_text("# none\n")
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "one")
    git(origin, "tag", "v1.0.0")
    (origin / "pump_gui.py").write_text("v2\n")
    git(origin, "commit", "-q", "-am", "two")
    git(origin, "tag", "v1.1.0")
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(work))
    git(work, "reset", "-q", "--hard", "v1.0.0")
    return origin, work


@needs_git
def test_update_fast_forwards_to_the_tag(clone):
    origin, work = clone
    assert updates.can_update(str(work)) == ""
    ok, message = updates.update_to(str(work), "v1.1.0")
    assert ok, message
    assert (work / "pump_gui.py").read_text() == "v2\n"


@needs_git
def test_update_refuses_hand_edited_files(clone):
    origin, work = clone
    (work / "pump_gui.py").write_text("my change\n")
    ok, message = updates.update_to(str(work), "v1.1.0")
    assert not ok and "changed by hand" in message
    assert (work / "pump_gui.py").read_text() == "my change\n"


@needs_git
def test_update_refuses_local_commits_not_in_the_release(clone):
    origin, work = clone
    (work / "extra.txt").write_text("x\n")
    git(work, "add", "extra.txt")
    git(work, "commit", "-q", "-m", "local")
    ok, message = updates.update_to(str(work), "v1.1.0")
    assert not ok and "aren't in the release" in message


@needs_git
def test_failed_dependency_install_rolls_back(clone):
    origin, work = clone
    (origin / "requirements.txt").write_text("this is not a requirement !!\n")
    git(origin, "commit", "-q", "-am", "bad deps")
    git(origin, "tag", "v1.2.0")
    ok, message = updates.update_to(str(work), "v1.2.0", python=sys.executable)
    assert not ok and "nothing was changed" in message
    assert (work / "pump_gui.py").read_text() == "v1\n"


def test_not_a_clone(tmp_path):
    assert "wasn't downloaded with git" in updates.can_update(str(tmp_path))
