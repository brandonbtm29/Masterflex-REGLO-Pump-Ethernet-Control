"""Run log CSV files that keep their columns straight.

Each row is a dict: the fixed columns below plus one column per metadata token. When a row
brings a column the file doesn't have yet (a token added after the file was started), the
file is rewritten with that column added, so old rows stay under their own headings instead
of values silently landing under the wrong ones. Older files whose rows are longer than their
header (written by earlier versions) are read with the extra values as "Extra 1", "Extra 2"...
No Qt here, so it can be tested on its own.
"""

import csv
import os
import shutil
import tempfile
from datetime import datetime

FIXED = ["Date/Time", "Event", "Mode", "Flow Rate", "Other Info"]


def read(path):
    """Return (header, rows) from a run log; ([], []) if it doesn't exist or is empty."""
    if not os.path.exists(path):
        return [], []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        rows = []
        for values in reader:
            if not any(values):
                continue
            row = dict(zip(header, values, strict=False))
            for i, extra in enumerate(values[len(header) :], start=1):
                row[f"Extra {i}"] = extra
            rows.append(row)
    for row in rows:  # extra columns from long rows join the header
        for key in row:
            if key not in header:
                header.append(key)
    return header, rows


def write(path, header, rows):
    """Replace the file in one step (a crash mid-write can't leave half a file)."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".runlog-", suffix=".csv", dir=folder)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for row in rows:
                writer.writerow([row.get(col, "") for col in header])
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _header_for(rows, start=None):
    header = list(start or FIXED)
    for row in rows:
        for key in row:
            if key not in header:
                header.append(key)
    return header


def append(path, rows):
    """Add rows to the end of a log, adding any new columns to the file first."""
    if isinstance(rows, dict):
        rows = [rows]
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        write(path, _header_for(rows), rows)
        return
    with open(path, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f), [])
    if all(key in header for row in rows for key in row):
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for row in rows:
                writer.writerow([row.get(col, "") for col in header])
        return
    old_header, old_rows = read(path)
    write(path, _header_for(rows, old_header), old_rows + rows)


def rewrite(path, rows, keep_copy=True):
    """Replace a log's rows, keeping the previous file as <name>.bak first."""
    header, _ = read(path)
    if keep_copy and os.path.exists(path):
        shutil.copy2(path, os.fspath(path) + ".bak")
    write(path, _header_for(rows, header or None), rows)


def key(row):
    """What identifies a logged event: time to the minute, event, mode and flow.

    Used to tell which runs in the backup log were also saved to run_log.csv, which may have
    been opened and re-saved in a spreadsheet (seconds dropped, US date format).
    """
    stamp = (row.get("Date/Time") or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            stamp = datetime.strptime(stamp, fmt).strftime("%Y-%m-%d %H:%M")
            break
        except ValueError:
            pass
    return (stamp, row.get("Event", ""), row.get("Mode", ""), row.get("Flow Rate", ""))
