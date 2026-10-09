"""PKG-09 (writer part): temp files, generated configurations and the audit log live in the local folder of this
PC; configurations of dead processes are removed, the audit log is capped."""
from __future__ import annotations

import os
import subprocess
import sys

from partforge import config
from partforge.altium import rustwriter


def test_writer_files_are_in_the_local_folder(monkeypatch, tmp_path):
    roaming, local = tmp_path / "Roaming", tmp_path / "Local"
    monkeypatch.setattr(rustwriter, "local_data_dir", lambda: local)
    monkeypatch.setattr(rustwriter, "log_dir", lambda: local / "logs")
    monkeypatch.setattr(config, "app_data_dir", lambda: roaming)
    (local / "logs").mkdir(parents=True)
    assert rustwriter.temp_dir() == local / "tmp" and rustwriter._runtime_dir() == local / "rustwriter"
    assert rustwriter.audit_log_path() == local / "logs" / "rustwriter-audit.jsonl"
    assert not roaming.exists()


def test_audit_log_is_rotated(monkeypatch, tmp_path):
    monkeypatch.setattr(rustwriter, "log_dir", lambda: tmp_path)
    log = tmp_path / "rustwriter-audit.jsonl"
    log.write_bytes(b"x" * (rustwriter.AUDIT_LOG_MAX_BYTES + 1))
    assert rustwriter.audit_log_path() == log and not log.exists()
    assert (tmp_path / "rustwriter-audit.1.jsonl").stat().st_size == rustwriter.AUDIT_LOG_MAX_BYTES + 1
    log.write_bytes(b"{}\n")
    rustwriter.audit_log_path()
    assert log.read_bytes() == b"{}\n"  # small logs stay


def test_configs_of_dead_processes_are_removed(tmp_path):
    dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    dead_pid = int(dead.stdout.strip())
    stale = tmp_path / f"config-{dead_pid}-1a2b3c.json"
    mine = tmp_path / f"config-{os.getpid()}-4d5e6f.json"
    other = tmp_path / "notes.txt"
    for path in (stale, mine, other):
        path.write_text("{}", encoding="utf-8")
    rustwriter._prune_stale_configs(tmp_path)
    assert not stale.exists() and mine.exists() and other.exists()
