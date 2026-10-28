"""updates.py: checking GitHub releases and fast-forwarding a git clone."""

import io
import json
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
from pathlib import Path

import pytest

import updates

REPO = Path(__file__).resolve().parent.parent
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


def head(work):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=work, check=True, capture_output=True, text=True
    ).stdout.strip()


def make_clone(tmp_path, branch="master"):
    """An 'origin' repo with v1.0.0 and v1.1.0, and a clone sitting at v1.0.0 on ``branch``."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", branch)
    (origin / "pump_gui.py").write_text("v1\n")
    (origin / "requirements.txt").write_text("# none\n")
    (origin / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = []\n')
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


@pytest.fixture
def clone(tmp_path):
    return make_clone(tmp_path)


def release(origin, tag, changes):
    """Commit ``changes`` ({file name: text}) in origin and tag the commit."""
    for name, text in changes.items():
        (origin / name).write_text(text)
    git(origin, "add", *changes)
    git(origin, "commit", "-q", "-m", tag)
    git(origin, "tag", tag)


@pytest.fixture
def fake_pip(monkeypatch):
    """Replace the dependency install with a quick command that succeeds; records each call."""
    calls = []

    def command(python=None):
        calls.append(python)
        return [sys.executable, "-c", "pass"]

    monkeypatch.setattr(updates, "install_command", command)
    return calls


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
    old = head(work)
    ok, message = updates.update_to(str(work), "v1.2.0", python=sys.executable)
    assert not ok and "failed, so the app went back to the version it had" in message
    assert head(work) == old
    assert (work / "pump_gui.py").read_text() == "v1\n"


def test_not_a_clone(tmp_path):
    assert "wasn't downloaded with git" in updates.can_update(str(tmp_path))


# --- branch names and dependencies --------------------------------------------------


@needs_git
@pytest.mark.parametrize("branch", ["master", "main", "lab-computer"])
def test_update_works_whatever_the_branch_is_called(tmp_path, branch):
    origin, work = make_clone(tmp_path, branch)
    ok, message = updates.update_to(str(work), "v1.1.0")
    assert ok, message
    assert (work / "pump_gui.py").read_text() == "v2\n"
    head = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"], cwd=work, capture_output=True, text=True
    )
    assert head.stdout.strip() == branch  # still on the same branch, moved forward


@needs_git
def test_update_works_on_a_copy_checked_out_at_a_tag(clone):
    origin, work = clone
    git(work, "checkout", "-q", "--detach", "v1.0.0")
    ok, message = updates.update_to(str(work), "v1.1.0")
    assert ok, message
    assert (work / "pump_gui.py").read_text() == "v2\n"


@needs_git
@pytest.mark.parametrize("changed", ["requirements.txt", "pyproject.toml"])
def test_dependency_change_reinstalls(clone, fake_pip, changed):
    origin, work = clone
    release(origin, "v1.2.0", {changed: "# new dependencies\n"})
    ok, message = updates.update_to(str(work), "v1.2.0")
    assert ok, message
    assert "Dependencies were updated" in message
    assert len(fake_pip) == 1
    assert updates.dependencies_changed(str(work), "v1.0.0", "v1.2.0")


@needs_git
def test_code_only_release_skips_the_reinstall(clone, fake_pip):
    origin, work = clone
    ok, message = updates.update_to(str(work), "v1.1.0")
    assert ok, message
    assert "Dependencies" not in message
    assert fake_pip == []
    assert not updates.dependencies_changed(str(work), "v1.0.0", "v1.1.0")


def test_reinstall_uses_the_setup_scripts_command():
    command = updates.install_command()
    args = " ".join(command[1:])
    assert args == "-m pip install -r requirements.txt"
    for script in ("Setup_Windows.bat", "Setup_Mac.command", "Launch_Windows.bat", "Launch_Mac.command"):
        assert args in (REPO / script).read_text(encoding="utf-8"), script


def test_pip_runs_with_the_console_python(tmp_path):
    (tmp_path / "python.exe").write_text("")
    assert updates.console_python(str(tmp_path / "pythonw.exe")) == str(tmp_path / "python.exe")
    assert updates.console_python(str(tmp_path / "python3")) == str(tmp_path / "python3")
    assert updates.install_command(str(tmp_path / "pythonw.exe"))[0] == str(tmp_path / "python.exe")


def _requirement_set(lines):
    return {line.split("#")[0].replace(" ", "").lower() for line in lines} - {""}


def test_requirements_txt_lists_the_same_packages_as_pyproject():
    # The launchers and Setup scripts install requirements.txt; pip install -e . uses pyproject.toml.
    # The updater reinstalls when either changes, so they must say the same thing.
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    from_pyproject = _requirement_set(project["dependencies"] + project["optional-dependencies"]["build"])
    from_requirements = _requirement_set((REPO / "requirements.txt").read_text(encoding="utf-8").splitlines())
    assert from_requirements == from_pyproject


# --- every failure after the move goes back; nothing waits for a prompt ------------------


def use_installer(monkeypatch, code):
    """Make the dependency install run ``python -c code`` instead of pip."""
    monkeypatch.setattr(updates, "install_command", lambda python=None: [sys.executable, "-c", code])


@pytest.fixture
def new_dependencies(clone):
    """The clone at v1.0.0, and a v1.2.0 that changes requirements.txt (so it reinstalls)."""
    origin, work = clone
    release(origin, "v1.2.0", {"requirements.txt": "# new dependencies\n"})
    return work, head(work)


def assert_went_back(work, old, message):
    assert "went back to the version it had" in message
    assert head(work) == old
    assert (work / "requirements.txt").read_text() == "# none\n"


@needs_git
def test_install_that_takes_too_long_is_stopped_and_rolled_back(new_dependencies, monkeypatch):
    work, old = new_dependencies
    # pip starts helper processes. Stopping only pip would leave them running (still installing,
    # and holding its output open, which would keep the update waiting), so the whole tree goes.
    use_installer(
        monkeypatch,
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)",
    )
    monkeypatch.setattr(updates, "INSTALL_TIMEOUT", 2)
    started = time.monotonic()
    ok, message = updates.update_to(str(work), "v1.2.0")
    assert time.monotonic() - started < 20
    assert not ok and "took longer than 2 seconds" in message
    assert_went_back(work, old, message)


@needs_git
def test_installer_that_cant_start_rolls_back(new_dependencies, monkeypatch, tmp_path):
    work, old = new_dependencies
    monkeypatch.setattr(updates, "install_command", lambda python=None: [str(tmp_path / "no-such-python")])
    ok, message = updates.update_to(str(work), "v1.2.0")
    assert not ok and "couldn't be started" in message
    assert_went_back(work, old, message)


@needs_git
def test_failing_installer_rolls_back_and_shows_its_output(new_dependencies, monkeypatch):
    work, old = new_dependencies
    use_installer(monkeypatch, "import sys; print('ERROR: No matching distribution found'); sys.exit(1)")
    ok, message = updates.update_to(str(work), "v1.2.0")
    assert not ok and "Installing the new dependencies failed" in message
    assert "No matching distribution found" in message
    assert_went_back(work, old, message)


@needs_git
def test_git_hanging_after_the_move_rolls_back(new_dependencies, monkeypatch):
    work, old = new_dependencies

    def hangs(*args, **kwargs):
        raise subprocess.TimeoutExpired(["git", "diff"], 60)

    monkeypatch.setattr(updates, "dependencies_changed", hangs)
    ok, message = updates.update_to(str(work), "v1.2.0")
    assert not ok and "Git stopped answering" in message
    assert_went_back(work, old, message)


@needs_git
def test_git_that_doesnt_answer_before_the_move_changes_nothing(new_dependencies, monkeypatch):
    work, old = new_dependencies
    real_git = updates._git

    def slow_fetch(root, *args, timeout=60):
        if args[0] == "fetch":
            raise subprocess.TimeoutExpired(["git", *args], timeout)
        return real_git(root, *args, timeout=timeout)

    monkeypatch.setattr(updates, "_git", slow_fetch)
    ok, message = updates.update_to(str(work), "v1.2.0")
    assert not ok and "took longer than 3 minutes" in message and "nothing was changed" in message
    assert head(work) == old


@needs_git
def test_git_and_pip_never_wait_for_a_sign_in_or_a_question(clone, monkeypatch):
    origin, work = clone
    shown = updates._git(
        str(work), "-c", 'alias.showenv=!echo "$GIT_TERMINAL_PROMPT $GCM_INTERACTIVE"', "showenv"
    )
    assert shown.stdout.split() == ["0", "never"]
    names = "'GIT_TERMINAL_PROMPT', 'GCM_INTERACTIVE', 'PIP_NO_INPUT'"
    use_installer(monkeypatch, f"import os; print(*(os.environ.get(k) for k in ({names})))")
    problem, output = updates.install_dependencies(str(work))
    assert problem == "" and output.split() == ["0", "never", "1"]
