"""Check GitHub for a newer release, and update a git clone of the app to it.

Checking asks GitHub's public API for the latest *release* of this repository (no account,
nothing about you is sent beyond a normal web request). Updating only works for a git clone:
it fast-forwards to the release tag, never to unreleased work, and refuses if any of the
app's own files were changed by hand. If the release changes requirements.txt, the
dependencies are reinstalled; if that fails, the clone goes back to where it was.
Standard library only, no Qt, so it can be tested on its own.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

REPO = "brandonbtm29/Masterflex-REGLO-Pump-Ethernet-Control"
RELEASES_URL = f"https://github.com/{REPO}/releases"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # don't flash console windows on Windows


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


def _git(root, *args, timeout=60):
    return subprocess.run(  # noqa: S603 - fixed arguments
        ["git", *args],  # noqa: S607 - git from PATH, like a person typing it
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
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
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    if status.returncode != 0:
        return "This folder's git information looks broken: " + status.stderr.strip()[:200]
    if status.stdout.strip():
        return "Some of the app's files were changed by hand, so updating could overwrite them."
    return ""


def update_to(root, tag, python=None):
    """Fast-forward the clone to ``tag`` and reinstall dependencies if they changed.

    Returns (ok, message). On failure the clone is put back where it was.
    """
    reason = can_update(root)
    if reason:
        return False, reason
    fetch = _git(root, "fetch", "--tags", "--force", "origin", timeout=180)
    if fetch.returncode != 0:
        return False, "Couldn't download from GitHub: " + fetch.stderr.strip()[:300]
    if _git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}").returncode != 0:
        return False, f"Release {tag} isn't available from GitHub yet."
    if _git(root, "merge-base", "--is-ancestor", "HEAD", tag).returncode != 0:
        return False, "This copy has changes that aren't in the release, so it can't update automatically."
    old = _git(root, "rev-parse", "HEAD").stdout.strip()
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    move = _git(root, "merge", "--ff-only", tag) if branch else _git(root, "checkout", "--quiet", tag)
    if move.returncode != 0:
        return False, "Couldn't switch to the new version: " + move.stderr.strip()[:300]

    changed = _git(root, "diff", "--quiet", old, "HEAD", "--", "requirements.txt").returncode != 0
    if changed:
        pip = subprocess.run(  # noqa: S603 - fixed arguments
            [python or sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            creationflags=NO_WINDOW,
        )
        if pip.returncode != 0:
            _git(root, "reset", "--keep", old)
            tail = (pip.stdout + pip.stderr).strip()[-400:]
            return False, f"Installing the new dependencies failed, so nothing was changed.\n\n{tail}"
    note = " Dependencies were updated too." if changed else ""
    return True, f"Updated to {tag}.{note}"
