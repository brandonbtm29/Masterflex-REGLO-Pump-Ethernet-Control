"""Check GitHub for a newer release, and update a git clone of the app to it.

Checking asks GitHub's public API for the latest *release* of this repository (no account,
nothing about you is sent beyond a normal web request). Updating only works for a git clone:
it fast-forwards to the release tag, never to unreleased work, and refuses if any of the
app's own files were changed by hand. It works whatever the clone's branch is called
(``master``, ``main``, ...) and on a clone checked out at a tag.

If the release changes the dependencies (requirements.txt, which the launchers and Setup
scripts install from, or pyproject.toml, which lists the same packages), they are reinstalled
with the same command the Setup scripts use. If anything goes wrong once the clone has moved
(the install fails, takes too long or can't start), the clone goes back to where it was.
Git and pip never wait for a password or a question nobody can see.
Standard library only, no Qt, so it can be tested on its own.
"""

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

log = logging.getLogger("masterflex_pump.updates")

REPO = "brandonbtm29/Masterflex-REGLO-Pump-Ethernet-Control"
RELEASES_URL = f"https://github.com/{REPO}/releases"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # don't flash console windows on Windows
REQUIREMENTS = "requirements.txt"  # what Setup_Windows.bat / Setup_Mac.command and the launchers install
# A release that changes either file gets its dependencies reinstalled. pyproject.toml lists the
# same packages (tests/test_updates.py checks the two stay in step).
DEPENDENCY_FILES = (REQUIREMENTS, "pyproject.toml")
FETCH_TIMEOUT = 180  # seconds for git to download the release
INSTALL_TIMEOUT = 900  # seconds (15 minutes) for pip to install the new dependencies
# The app has no console, so nobody could answer a git sign-in prompt or a pip question:
# git would wait forever. Make both fail straight away instead.
QUIET_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",  # Git Credential Manager (Windows, macOS): no sign-in window
    "PIP_NO_INPUT": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
}


def parse_version(text):
    """'v1.2.0' -> (1, 2, 0). Pre-releases and odd tags give None."""
    m = _VERSION.match((text or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def is_newer(candidate, current):
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


@dataclass
class Release:
    version: str  # "1.2.0"
    tag: str  # "v1.2.0"
    notes: str
    url: str


def latest_release(current_version, timeout=10, opener=urllib.request.urlopen):
    """The newest published release. Raises LookupError with a readable message on problems."""
    request = urllib.request.Request(
        API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"masterflex-reglo/{current_version}",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LookupError("No releases have been published yet.") from e
        raise LookupError(f"GitHub answered with an error ({e.code}). Try again later.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LookupError("Couldn't reach GitHub. Check the internet connection.") from e
    except ValueError as e:
        raise LookupError("GitHub sent something unexpected.") from e
    tag = str(data.get("tag_name") or "")
    version = parse_version(tag)
    if version is None:
        raise LookupError(f"The latest release tag {tag!r} isn't a version number.")
    return Release(
        version=".".join(map(str, version)),
        tag=tag,
        notes=str(data.get("body") or "")[:20000],
        url=str(data.get("html_url") or RELEASES_URL),
    )


def _quiet_env():
    return {**os.environ, **QUIET_ENV}


def _git(root, *args, timeout=60):
    """Run git. Raises subprocess.TimeoutExpired or OSError if it hangs or can't start."""
    return subprocess.run(  # noqa: S603 - fixed arguments
        ["git", *args],  # noqa: S607 - git from PATH, like a person typing it
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        env=_quiet_env(),
        creationflags=NO_WINDOW,
    )


def can_update(root):
    """'' if this copy can update itself with git, else the reason it can't, in plain words."""
    if getattr(sys, "frozen", False):
        return "This is a built app. Download the new version from the releases page instead."
    if not os.path.isdir(os.path.join(root, ".git")):
        return "This copy wasn't downloaded with git, so it can't update itself."
    if shutil.which("git") is None:
        return "Git isn't installed on this computer, so the app can't update itself."
    try:
        status = _git(root, "status", "--porcelain", "--untracked-files=no")
    except (subprocess.TimeoutExpired, OSError) as e:
        return f"Git couldn't check this folder ({_short(e)}), so the app can't update itself right now."
    if status.returncode != 0:
        return "This folder's git information looks broken: " + status.stderr.strip()[:200]
    if status.stdout.strip():
        return "Some of the app's files were changed by hand, so updating could overwrite them."
    return ""


def console_python(executable=None):
    """The python.exe next to pythonw.exe. The app runs windowless under pythonw.exe on
    Windows, but pip should run under the normal one, like the Setup scripts do."""
    exe = executable or sys.executable
    folder, name = os.path.split(exe)
    if name.lower() == "pythonw.exe":
        candidate = os.path.join(folder, "python.exe")
        if os.path.exists(candidate):
            return candidate
    return exe


def install_command(python=None):
    """The command Setup_Windows.bat / Setup_Mac.command use to install what the app needs."""
    return [console_python(python), "-m", "pip", "install", "-r", REQUIREMENTS]


def dependencies_changed(root, old, new="HEAD"):
    """True if requirements.txt or pyproject.toml differ between two commits (or git can't tell)."""
    return _git(root, "diff", "--quiet", old, new, "--", *DEPENDENCY_FILES).returncode != 0


def _short(error):
    """One line about an error from starting or waiting for git or pip."""
    if isinstance(error, subprocess.TimeoutExpired):
        return f"no answer after {_duration(error.timeout)}"
    return str(error) or type(error).__name__


def _duration(seconds):
    return f"{seconds // 60:g} minutes" if seconds >= 120 else f"{seconds:g} seconds"


def _kill_tree(proc):
    """Stop pip and the helper processes it started (packages are built in processes of their
    own), so nothing carries on installing after the clone has gone back."""
    try:
        if os.name == "nt":
            subprocess.run(  # noqa: S603 - fixed arguments
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],  # noqa: S607 - Windows' own tool
                capture_output=True,
                timeout=30,
                creationflags=NO_WINDOW,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)  # pip was started as the leader of its own group
    except (OSError, subprocess.SubprocessError):
        pass  # already gone
    proc.kill()


def install_dependencies(root, python=None):
    """Install what the app needs, the way the Setup scripts do; give up after INSTALL_TIMEOUT.

    Returns (problem, output): ``problem`` is "" if it worked, else what went wrong in plain words.
    """
    try:
        proc = subprocess.Popen(  # noqa: S603 - fixed arguments
            install_command(python),
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_quiet_env(),
            creationflags=NO_WINDOW,
            start_new_session=os.name != "nt",  # its own process group, so a timeout stops it all
        )
    except OSError as e:
        return f"The installer for the new dependencies couldn't be started ({e})", ""
    try:
        output, _ = proc.communicate(timeout=INSTALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            output, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            output = ""
        return f"Installing the new dependencies took longer than {_duration(INSTALL_TIMEOUT)}", output or ""
    if proc.returncode != 0:
        return "Installing the new dependencies failed", output
    return "", output


def _go_back(root, old, why, detail=""):
    """Put the clone back on commit ``old`` after a failed update. Returns (False, message)."""
    log.error("%s; going back to %s.%s", why, old[:10], f"\n{detail}" if detail else "")
    try:
        back = _git(root, "reset", "--keep", old)
        problem = "" if back.returncode == 0 else back.stderr.strip()[:300]
    except (subprocess.TimeoutExpired, OSError) as e:
        problem = _short(e)
    if problem:
        log.error("Going back to %s failed: %s", old[:10], problem)
        message = (
            f"{why}. Going back to the previous version didn't work either ({problem}). "
            "Run Setup_Windows.bat or Setup_Mac.command to reinstall what the app needs."
        )
    else:
        message = f"{why}, so the app went back to the version it had."
    return False, f"{message}\n\n{detail}" if detail else message


def update_to(root, tag, python=None):
    """Fast-forward the clone to ``tag`` and reinstall dependencies if they changed.

    Returns (ok, message) and doesn't raise. Once the clone has moved, every failure (the
    install fails, takes too long or can't start; git stops answering) puts it back where it was.
    """
    try:
        reason = can_update(root)
        if reason:
            return False, reason
        fetch = _git(root, "fetch", "--tags", "--force", "origin", timeout=FETCH_TIMEOUT)
        if fetch.returncode != 0:
            return False, "Couldn't download from GitHub: " + fetch.stderr.strip()[:300]
        if _git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}").returncode != 0:
            return False, f"Release {tag} isn't available from GitHub yet."
        if _git(root, "merge-base", "--is-ancestor", "HEAD", tag).returncode != 0:
            return (
                False,
                "This copy has changes that aren't in the release, so it can't update automatically.",
            )
        head = _git(root, "rev-parse", "HEAD")
        if head.returncode != 0:
            return False, "Couldn't tell which version this copy is on: " + head.stderr.strip()[:300]
        old = head.stdout.strip()
        branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    except subprocess.TimeoutExpired as e:
        return False, (
            f"Git took longer than {_duration(e.timeout)} to answer, so nothing was changed. "
            "Check the internet connection and try again."
        )
    except OSError as e:
        return False, f"Git couldn't be started ({e}), so nothing was changed."

    # From here on the clone may have moved, so every failure goes back to ``old``.
    try:
        move = _git(root, "merge", "--ff-only", tag) if branch else _git(root, "checkout", "--quiet", tag)
        if move.returncode != 0:  # git refused and left everything as it was
            return False, "Couldn't switch to the new version: " + move.stderr.strip()[:300]
        changed = dependencies_changed(root, old)
        if changed:
            problem, output = install_dependencies(root, python)
            if problem:
                return _go_back(root, old, problem, output.strip()[-400:])
    except subprocess.TimeoutExpired as e:
        return _go_back(root, old, f"Git stopped answering during the update ({_short(e)})")
    except Exception as e:  # anything else: still never leave the clone half-updated
        log.exception("Updating to %s failed", tag)
        return _go_back(root, old, f"The update stopped with an error ({e})")
    log.info("Updated from %s to %s", old[:10], tag)
    note = " Dependencies were updated too." if changed else ""
    return True, f"Updated to {tag}.{note}"
