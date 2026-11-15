"""scripts/heavy.py: the lock and a queue entry count only while the process that wrote them still runs.

Windows hands a dead process's pid to a new process, so the pid in an old lock or queue entry can be running and
belong to somebody else."""
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BEFORE_THIS_PROCESS = time.time() - 14 * 86400
SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="heavy.py asks Windows about its processes")


@pytest.fixture
def heavy(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("heavy", ROOT / "scripts" / "heavy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "LOCK", str(tmp_path / "HEAVY.lock"))
    monkeypatch.setattr(module, "QUEUE", str(tmp_path / "HEAVY.queue"))
    os.mkdir(module.QUEUE)
    return module


@pytest.fixture
def ended():
    """a process that ended; holding it keeps Windows from giving its pid away during the test"""
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process


def write_at(path, text, written_at):
    path.write_text(text)
    if written_at is not None:
        os.utime(path, (written_at, written_at))


def queue_entry(heavy, prio, pid, written_at=None):
    path = Path(heavy.QUEUE) / ("%d_job_%d" % (prio, pid))
    write_at(path, "python job.py\n", written_at)
    return path.name


def lock(heavy, text, written_at=None):
    write_at(Path(heavy.LOCK), text, written_at)


def test_a_running_waiter_with_a_higher_priority_is_waited_for(heavy):
    entry = queue_entry(heavy, 7, os.getpid())
    assert heavy.higher_waiter(5) == entry
    assert heavy.higher_waiter(7) is None


def test_an_entry_whose_pid_went_to_a_later_process_is_not_a_waiter(heavy):
    queue_entry(heavy, 7, os.getpid(), written_at=BEFORE_THIS_PROCESS)
    assert heavy.higher_waiter(5) is None


def test_an_entry_of_an_ended_process_is_not_a_waiter(heavy, ended):
    queue_entry(heavy, 7, ended.pid)
    assert heavy.higher_waiter(5) is None


def test_a_lock_whose_holder_runs_stays(heavy):
    lock(heavy, "job prio 5 pid %d since now: python job.py\n" % os.getpid())
    heavy.clear_stale_lock()
    assert os.path.exists(heavy.LOCK)


def test_a_lock_whose_pid_went_to_a_later_process_is_removed(heavy):
    lock(heavy, "job prio 5 pid %d since then: python job.py\n" % os.getpid(), written_at=BEFORE_THIS_PROCESS)
    heavy.clear_stale_lock()
    assert not os.path.exists(heavy.LOCK)


def test_a_lock_of_an_ended_process_is_removed(heavy, ended):
    lock(heavy, "job prio 5 pid %d since now: python job.py\n" % ended.pid)
    heavy.clear_stale_lock()
    assert not os.path.exists(heavy.LOCK)


def test_a_lock_that_names_no_pid_stays(heavy):
    lock(heavy, "held by hand\n", written_at=BEFORE_THIS_PROCESS)
    heavy.clear_stale_lock()
    assert os.path.exists(heavy.LOCK)


def test_a_lock_taken_by_another_job_while_the_old_one_was_judged_stays(heavy, ended, monkeypatch):
    lock(heavy, "old prio 5 pid %d since then: python job.py\n" % ended.pid)
    new_lock = "new prio 5 pid %d since now: python job.py\n" % os.getpid()

    def old_holder_is_gone_and_a_new_job_takes_the_lock(path, pid):
        lock(heavy, new_lock)
        return False

    monkeypatch.setattr(heavy, "writer_runs", old_holder_is_gone_and_a_new_job_takes_the_lock)
    heavy.clear_stale_lock()
    assert Path(heavy.LOCK).read_text() == new_lock


def stop(process):
    process.kill()
    process.wait()


@pytest.fixture
def sleeper():
    process = subprocess.Popen(SLEEP)
    yield process
    stop(process)


def test_a_process_start_time_is_when_it_was_started(heavy):
    before = time.time()
    child = subprocess.Popen(SLEEP)
    after = time.time()
    try:
        started = heavy.process_started_at(child.pid)
    finally:
        stop(child)
    assert before - 1 <= started <= after + 1


def test_an_entry_written_ten_seconds_before_its_pid_started_is_not_a_waiter(heavy, sleeper):
    queue_entry(heavy, 7, sleeper.pid, written_at=time.time() - 10)
    assert heavy.higher_waiter(5) is None


def test_an_entry_that_is_gone_has_no_running_writer(heavy, tmp_path):
    assert not heavy.writer_runs(str(tmp_path / "absent"), os.getpid())


def test_a_pid_that_no_process_has_did_not_start(heavy):
    assert heavy.process_started_at(0xFFFFFFF0) is None


def test_the_job_runs_under_a_lock_that_reads_as_held(heavy, monkeypatch):
    seen = {}

    def job(cmd, log):
        seen["held"] = heavy.writer_runs(heavy.LOCK, os.getpid())
        heavy.clear_stale_lock()
        seen["kept"] = os.path.exists(heavy.LOCK)
        seen["queued"] = os.listdir(heavy.QUEUE)
        return 7

    monkeypatch.setattr(heavy, "run", job)
    monkeypatch.setattr(heavy, "avail_gb", lambda: 99.0)
    monkeypatch.setattr(sys, "argv", ["heavy.py", "job", "--", "python", "job.py"])
    assert heavy.main() == 7
    assert seen == {"held": True, "kept": True, "queued": []}
    assert not os.path.exists(heavy.LOCK)
