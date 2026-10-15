"""runlog.py: run log CSVs keep their columns aligned."""

import csv

import runlog


def rows_of(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def row(stamp, event="START", **tokens):
    return {
        "Date/Time": stamp,
        "Event": event,
        "Mode": "Time",
        "Flow Rate": "5 mL/min",
        "Other Info": "",
        **tokens,
    }


def test_new_file_gets_a_header(tmp_path):
    path = tmp_path / "log.csv"
    runlog.append(path, row("2026-10-14 10:00:00", Column="A"))
    assert rows_of(path)[0] == runlog.FIXED + ["Column"]
    assert rows_of(path)[1][-1] == "A"


def test_new_token_adds_a_column_and_keeps_old_rows_in_place(tmp_path):
    path = tmp_path / "log.csv"
    runlog.append(path, row("2026-10-14 10:00:00", Column="A"))
    runlog.append(path, row("2026-10-14 10:05:00", Column="B", Run="2"))
    runlog.append(path, row("2026-10-14 10:10:00", Run="3"))  # Column token removed
    header, rows = runlog.read(path)
    assert header == runlog.FIXED + ["Column", "Run"]
    assert [(r["Column"], r["Run"]) for r in rows] == [("A", ""), ("B", "2"), ("", "3")]


def test_legacy_rows_longer_than_the_header_are_kept(tmp_path):
    path = tmp_path / "log.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(runlog.FIXED + ["Column"])
        w.writerow(["2026-09-01 09:00:00", "START", "Volume", "1 mL/min", "", "A", "late token"])
    header, rows = runlog.read(path)
    assert header[-1] == "Extra 1" and rows[0]["Extra 1"] == "late token"
    runlog.append(path, row("2026-10-14 10:00:00", Column="B"))
    assert runlog.read(path)[1][0]["Extra 1"] == "late token"


def test_rewrite_keeps_a_copy(tmp_path):
    path = tmp_path / "log.csv"
    runlog.append(path, [row("2026-10-14 10:00:00"), row("2026-10-14 11:00:00")])
    runlog.rewrite(path, [row("2026-10-14 11:00:00")])
    assert len(runlog.read(path)[1]) == 1
    assert len(runlog.read(str(path) + ".bak")[1]) == 2


def test_key_matches_spreadsheet_edited_rows():
    a = row("2026-10-14 10:00:42")
    b = dict(a, **{"Date/Time": "10/14/2026 10:00"})
    assert runlog.key(a) == runlog.key(b)
