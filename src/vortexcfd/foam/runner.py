"""OpenFOAM process runner module.

Provides:
- run_foam(): simple blocking runner (original API, unchanged).
- FoamRun: streaming runner with live line callbacks, timeout, and signal-based clean stop.
- RunResult: dataclass returned by FoamRun.result().
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import signal
import subprocess
import threading
import time
from typing import Callable

from vortexcfd.foam.dictfile import read_foam_file

OPENFOAM_BASHRC = Path("/usr/lib/openfoam/openfoam2606/etc/bashrc")


def session_pids(sid: int) -> list[int]:
    """Live processes of session ``sid`` (from /proc/<pid>/stat; zombies left out).

    FoamRun starts every command in a new session, and mpirun puts each rank in a process group
    of its own but in that session, so the session holds the whole process tree."""
    out = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        fields = stat[stat.rfind(")") + 2:].split()
        if len(fields) > 3 and fields[0] != "Z" and int(fields[3]) == sid:
            out.append(int(entry.name))
    return out


def signal_session(sid: int, sig: int) -> int:
    """Send ``sig`` to every live process of session ``sid``; returns how many were signalled."""
    count = 0
    for pid in session_pids(sid):
        try:
            os.kill(pid, sig)
            count += 1
        except (ProcessLookupError, PermissionError):
            pass
    return count


def run_foam(command: list[str], case_dir: Path, log_file: Path) -> int:
    """Run an OpenFOAM command with the OpenFOAM environment loaded.

    Sources /usr/lib/openfoam/openfoam2606/etc/bashrc explicitly, runs the
    specified command within the given case directory, writes combined
    stdout and stderr to log_file, and returns the process exit code.

    Args:
        command: Command and arguments to execute (e.g., ["blockMesh"]).
        case_dir: Working directory for the OpenFOAM case.
        log_file: Path where stdout and stderr will be written.

    Returns:
        Process exit code.
    """
    if not command:
        raise ValueError("command must not be empty")

    case_path = Path(case_dir)
    log_path = Path(log_file)

    log_path.parent.mkdir(parents=True, exist_ok=True)

    cmd_str = shlex.join(command)
    shell_cmd = f"source {shlex.quote(str(OPENFOAM_BASHRC))} && exec {cmd_str}"

    with open(log_path, "w", encoding="utf-8") as f:
        result = subprocess.run(
            ["bash", "-c", shell_cmd],
            cwd=case_path,
            stdout=f,
            stderr=subprocess.STDOUT,
            check=False,
        )

    return result.returncode


@dataclass
class RunResult:
    """Result of a completed FoamRun.

    Attributes:
        exit_code: Process exit code, or negative signal number if killed.
        duration_s: Wall-clock run duration in seconds.
        log_file: Path to the generated log file.
        stopped_by_user: Alias for stop_requested (True if stop was requested while alive).
        stop_requested: True if an orderly stop was registered while the process was running.
        stop_mode: Mode of stopping if requested. One of "none", "clean", "terminated", "killed".
            - "none": stop was not requested.
            - "clean": stop was requested and process exited with code 0.
            - "terminated": process was ended by SIGTERM (exit code -15 / 143), or exited with
              an unexpected non-zero code after stop was requested.
            - "killed": process was ended by SIGKILL (exit code -9 / 137).
        timed_out: True if the process exceeded timeout_s while still running.
        callback_errors: Number of exceptions caught and suppressed during on_line calls.
        orphans_killed: Processes of the run's session still alive after the main process ended
            (e.g. MPI ranks), killed by the final sweep.
    """

    exit_code: int | None
    duration_s: float
    log_file: Path
    stopped_by_user: bool = False
    stop_requested: bool = False
    stop_mode: str = "none"
    timed_out: bool = False
    callback_errors: int = 0
    orphans_killed: int = 0


class FoamRun:
    """Streaming OpenFOAM process runner with live line callbacks and clean stop.

    Threading model:
    - start() spawns the subprocess in a new session (start_new_session=True) and a reader thread.
    - The reader thread reads stdout+stderr line by line, writes each line to log_file
      immediately (with flush), and calls on_line(line) if given.
    - on_line runs in the reader thread, NOT the main thread.
    - Exceptions inside on_line are caught, counted, and never kill the reader.
    - lines keeps up to keep_last_lines lines in memory (FIFO via collections.deque).
      The full log is always written to disk in log_file.
    - wait() blocks until the process finishes, returning a bool indicating completion.
    - request_stop() is non-blocking and thread-safe. It initiates signal escalation in a
      background watchdog thread.
    - stop() is a blocking convenience wrapper around request_stop().
    """

    def __init__(self, keep_last_lines: int = 1000) -> None:
        """Initialize a FoamRun instance.

        Args:
            keep_last_lines: Maximum number of recent lines to retain in memory (default: 1000).
        """
        self._keep_last_lines: int = keep_last_lines
        self._lines: deque[str] = deque(maxlen=keep_last_lines)
        self._lock = threading.Lock()
        self._done_event = threading.Event()
        self._gate_opened = threading.Event()

        self._started: bool = False
        self._stop_requested: bool = False
        self._clean_stop: bool = False
        self._escalated_to_term: bool = False
        self._escalated_to_kill: bool = False
        self._timed_out: bool = False
        self._callback_errors: int = 0
        self._orphans_killed: int = 0

        self._start_time: float = 0.0
        self._end_time: float | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._timeout_thread: threading.Thread | None = None
        self._stop_thread: threading.Thread | None = None

        self._log_file_handle: object | None = None
        self._log_file_path: Path | None = None
        self._case_dir: Path | None = None
        self._on_line: Callable[[str], None] | None = None
        self._timeout_s: float | None = None

    def start(
        self,
        command: list[str],
        case_dir: Path,
        log_file: Path,
        *,
        on_line: Callable[[str], None] | None = None,
        timeout_s: float | None = None,
        clean_stop: bool = False,
        keep_last_lines: int | None = None,
        append: bool = False,
    ) -> None:
        """Start an OpenFOAM command asynchronously.

        Args:
            command: Command and arguments (e.g., ["icoFoam"]).
            case_dir: Working directory for the OpenFOAM case.
            log_file: Path where stdout+stderr will be written.
            on_line: Optional callback invoked for each output line (runs in reader thread).
            timeout_s: Optional wall-clock timeout in seconds.
            clean_stop: If True, request_stop() sends SIGUSR1 once the solver has entered its
                time-stepping loop ("Time = " gate). If False, stops escalate directly to SIGTERM.
            keep_last_lines: Optional override for the in-memory line buffer size.
            append: Append to log_file instead of replacing it (the second turbulence stage, D-126).

        Raises:
            ValueError: If command is empty, or if clean_stop=True and the case's
                system/controlDict does not set OptimisationSwitches.stopAtWriteNowSignal
                to int(signal.SIGUSR1).
            RuntimeError: If start() has already been called on this instance.
        """
        if not command:
            raise ValueError("command must not be empty")

        if clean_stop:
            self._validate_clean_stop_switch(Path(case_dir))

        with self._lock:
            if self._started:
                raise RuntimeError("start() has already been called on this FoamRun instance")
            self._started = True
            self._clean_stop = clean_stop
            if keep_last_lines is not None:
                self._keep_last_lines = keep_last_lines
                self._lines = deque(maxlen=keep_last_lines)

        self._log_file_path = Path(log_file)
        self._log_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._case_dir = Path(case_dir)
        self._on_line = on_line
        self._timeout_s = timeout_s

        cmd_str = shlex.join(command)
        shell_cmd = (
            f"source {shlex.quote(str(OPENFOAM_BASHRC))} && exec {cmd_str}"
        )

        self._log_file_handle = open(  # append: a run continued in the same log (D-126)
            self._log_file_path, "a" if append else "w", encoding="utf-8"
        )
        self._start_time = time.monotonic()
        self._process = subprocess.Popen(
            ["bash", "-c", shell_cmd],
            cwd=self._case_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        self._reader_thread = threading.Thread(
            target=self._read_output, daemon=True
        )
        self._reader_thread.start()

        if timeout_s is not None:
            self._timeout_thread = threading.Thread(
                target=self._timeout_watcher, daemon=True
            )
            self._timeout_thread.start()

    @staticmethod
    def _validate_clean_stop_switch(case_dir: Path) -> None:
        """Ensure controlDict makes OpenFOAM handle SIGUSR1, else the signal kills the solver."""
        expected = int(signal.SIGUSR1)
        control_dict = case_dir / "system" / "controlDict"
        actual = None
        if control_dict.is_file():
            try:
                switches = read_foam_file(control_dict).get("OptimisationSwitches")
            except Exception as exc:  # foamlib raises assorted parser exceptions
                raise ValueError(
                    f"clean_stop=True requires a readable {control_dict}, but it cannot be "
                    f"parsed ({type(exc).__name__}: {exc}). Use "
                    f"vortexcfd.foam.case_writer.enable_clean_stop() to generate it."
                ) from exc
            actual = switches.get("stopAtWriteNowSignal") if isinstance(switches, dict) else None
        if actual != expected:
            raise ValueError(
                f"clean_stop=True requires OptimisationSwitches.stopAtWriteNowSignal = "
                f"{expected} in {control_dict} (found {actual!r}); without it SIGUSR1 kills "
                f"the solver without writing. Use vortexcfd.foam.case_writer.enable_clean_stop()."
            )

    def _read_output(self) -> None:
        """Reader thread: read lines from stdout, detect time step gate, write log."""
        assert self._process is not None
        assert self._process.stdout is not None
        assert self._log_file_handle is not None
        try:
            for raw_line in self._process.stdout:
                line = raw_line.decode("utf-8", errors="replace")

                # Gate detection must not depend on on_line callback
                if not self._gate_opened.is_set() and line.startswith("Time = "):
                    self._gate_opened.set()

                with self._lock:
                    self._lines.append(line)
                self._log_file_handle.write(line)  # type: ignore[union-attr]
                self._log_file_handle.flush()  # type: ignore[union-attr]

                if self._on_line is not None:
                    try:
                        self._on_line(line)
                    except Exception:
                        with self._lock:
                            self._callback_errors += 1
        finally:
            self._process.stdout.close()
            self._process.wait()
            # The session's other processes (MPI ranks) must not outlive the run.
            self._orphans_killed = signal_session(self._process.pid, signal.SIGKILL)
            self._end_time = time.monotonic()
            self._log_file_handle.close()  # type: ignore[union-attr]
            self._done_event.set()

    def _timeout_watcher(self) -> None:
        """Timeout thread: wait for timeout_s then terminate the process."""
        assert self._timeout_s is not None
        if self._done_event.wait(timeout=self._timeout_s):
            return  # Process finished before timeout

        with self._lock:
            if self._done_event.is_set():
                return
            self._timed_out = True
        self._terminate_process_group()

    def _terminate_process_group(self, grace_s: float = 2.0) -> None:
        """Send SIGTERM to the process group, then SIGKILL after grace period."""
        if self._process is None or self._done_event.is_set():
            return
        if not self._signal_tree(signal.SIGTERM):
            return

        if self._done_event.wait(timeout=grace_s):
            return

        self._signal_tree(signal.SIGKILL)

    def _signal_tree(self, sig: int) -> bool:
        """Send ``sig`` to the process group and to every process of the run's session (MPI
        ranks have process groups of their own). False when nothing was left to signal."""
        assert self._process is not None
        sent = False
        try:
            os.killpg(os.getpgid(self._process.pid), sig)
            sent = True
        except (ProcessLookupError, PermissionError):
            pass
        return signal_session(self._process.pid, sig) > 0 or sent

    def is_running(self) -> bool:
        """Return True if the process has been started and is still running."""
        with self._lock:
            started = self._started
        return started and not self._done_event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the process finishes.

        Args:
            timeout: Maximum time to wait in seconds. None means wait forever.

        Returns:
            True if the process finished, False if the timeout expired.

        Raises:
            RuntimeError: If start() has not been called.
        """
        with self._lock:
            if not self._started:
                raise RuntimeError("start() has not been called")
        return self._done_event.wait(timeout=timeout)

    def request_stop(self, grace_s: float = 10.0) -> bool:
        """Request an orderly stop of the running process asynchronously.

        This method is non-blocking, thread-safe, and idempotent. It returns in well
        under 100 ms. All waiting and escalation happen in a background watchdog thread.

        If clean_stop=True:
            Sends SIGUSR1 to the solver process (child PID; shell replaced by exec; for
            ``mpirun ... -parallel`` that is mpirun, and Open MPI forwards SIGUSR1 to the ranks),
            gated on the process having printed its first line starting with "Time = ".
            If the stop is requested before the gate opens, it waits up to 30 s for
            the gate. If the gate does not open in 30 s, it escalates to terminate.
            If the process does not exit within grace_s after SIGUSR1, it escalates
            to SIGTERM, then after 2 more seconds to SIGKILL.

        If clean_stop=False:
            Escalates directly to terminate (SIGTERM to the process group, followed
            by SIGKILL if it does not exit within grace_s).

        Args:
            grace_s: Seconds to wait for clean exit before escalating signals.

        Returns:
            True if this call registered a stop on a still-running process, False
            otherwise (not started, already finished, or already requested).
        """
        with self._lock:
            if not self._started:
                return False
            if self._done_event.is_set():
                return False
            if self._stop_requested:
                return False
            self._stop_requested = True

            self._stop_thread = threading.Thread(
                target=self._stop_watchdog,
                args=(grace_s,),
                daemon=True,
            )
            self._stop_thread.start()
            return True

    def _stop_watchdog(self, grace_s: float) -> None:
        """Watchdog thread handling clean signal delivery and escalation."""
        assert self._process is not None
        pid = self._process.pid

        if self._clean_stop:
            # Gate: wait up to 30 s for first "Time = " line
            gate_opened = self._gate_opened.wait(timeout=30.0)
            if self._done_event.is_set():
                return

            if not gate_opened:
                # Gate did not open within 30 s: escalate to terminate
                self._escalate_termination(grace_s)
                return

            # Gate is open: send SIGUSR1 to the solver process
            try:
                if self._process.poll() is None:
                    os.kill(pid, signal.SIGUSR1)
            except (ProcessLookupError, PermissionError):
                return

            # Wait grace_s for clean exit
            if self._done_event.wait(timeout=grace_s):
                return

            # No exit after grace_s: escalate to SIGTERM (with 2 s grace before SIGKILL)
            self._escalate_termination(grace_s=2.0)
        else:
            # clean_stop=False: go straight to terminate
            self._escalate_termination(grace_s)

    def _escalate_termination(self, grace_s: float) -> None:
        """Escalate to SIGTERM, then SIGKILL to the process group."""
        assert self._process is not None
        if self._done_event.is_set():
            return

        with self._lock:
            self._escalated_to_term = True
        if not self._signal_tree(signal.SIGTERM):
            return

        if self._done_event.wait(timeout=grace_s):
            return

        with self._lock:
            self._escalated_to_kill = True
        if not self._signal_tree(signal.SIGKILL):
            return

        self._done_event.wait(timeout=5.0)

    def stop(self, grace_s: float = 10.0) -> None:
        """Request an orderly stop of the running process and block until it finishes.

        This is a blocking convenience wrapper around :meth:`request_stop`. It initiates
        the stop sequence (via SIGUSR1 if clean_stop=True and the gate has opened, or
        via SIGTERM if clean_stop=False) and blocks the calling thread until the process
        exits. If the process does not exit within grace_s, escalation to SIGTERM and/or
        SIGKILL is applied.

        Args:
            grace_s: Seconds to wait for orderly exit before escalating signals.
        """
        with self._lock:
            if not self._started:
                return
        self.request_stop(grace_s=grace_s)
        self.wait()

    def result(self) -> RunResult:
        """Return the result of the completed run.

        Raises:
            RuntimeError: If the process has not finished yet.
        """
        if not self._done_event.is_set():
            raise RuntimeError("Process has not finished yet")
        assert self._process is not None
        assert self._log_file_path is not None

        duration = (self._end_time or time.monotonic()) - self._start_time

        with self._lock:
            stop_requested = self._stop_requested
            stopped_by_user = self._stop_requested
            timed_out = self._timed_out
            callback_errors = self._callback_errors
            ret_code = self._process.returncode
            escalated_to_term = self._escalated_to_term
            escalated_to_kill = self._escalated_to_kill
            orphans_killed = self._orphans_killed

        stop_mode = "none"
        if stop_requested:
            if ret_code == 0:
                stop_mode = "clean"
            elif ret_code in (-signal.SIGKILL, 128 + signal.SIGKILL) or escalated_to_kill:
                stop_mode = "killed"
            elif ret_code in (-signal.SIGTERM, 128 + signal.SIGTERM) or escalated_to_term:
                stop_mode = "terminated"
            else:
                # If stop was requested and process ended with any other code,
                # classify as "terminated" (interrupted / aborted).
                stop_mode = "terminated"

        return RunResult(
            exit_code=ret_code,
            duration_s=duration,
            log_file=self._log_file_path,
            stopped_by_user=stopped_by_user,
            stop_requested=stop_requested,
            stop_mode=stop_mode,
            timed_out=timed_out,
            callback_errors=callback_errors,
            orphans_killed=orphans_killed,
        )

    @property
    def lines(self) -> list[str]:
        """Return a snapshot of up to the last keep_last_lines lines received so far.

        The complete log is always preserved on disk in the log_file.
        """
        with self._lock:
            return list(self._lines)
