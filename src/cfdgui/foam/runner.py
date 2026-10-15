"""OpenFOAM process runner module.

Provides:
- run_foam(): simple blocking runner (original API, unchanged).
- FoamRun: streaming runner with live line callbacks, timeout, and clean stop.
- RunResult: dataclass returned by FoamRun.result().
"""

from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess
import threading
from typing import Callable

OPENFOAM_BASHRC = Path("/usr/lib/openfoam/openfoam2606/etc/bashrc")


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
    """Result of a completed FoamRun."""

    exit_code: int | None
    duration_s: float
    log_file: Path
    stopped_by_user: bool = False
    timed_out: bool = False
    callback_errors: int = 0


class FoamRun:
    """Streaming OpenFOAM process runner with live line callbacks.

    Threading model:
    - start() spawns the subprocess and a reader thread.
    - The reader thread reads stdout+stderr line by line, writes each line
      to log_file immediately (with flush), and calls on_line(line) if given.
    - on_line runs in the reader thread, NOT the main thread.
    - Exceptions inside on_line are caught, counted, and never kill the reader.
    - wait() and stop() block the calling thread until the process finishes.
    - The subprocess is started in its own process session (os.setsid) so that
      stop() can signal the entire process group.

    Environment:
    - OpenFOAM's bashrc is sourced explicitly; OpenFOAM is never assumed on PATH.
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._log_file_handle: object | None = None
        self._log_file_path: Path | None = None
        self._case_dir: Path | None = None
        self._start_time: float = 0.0
        self._end_time: float | None = None
        self._stopped_by_user: bool = False
        self._timed_out: bool = False
        self._callback_errors: int = 0
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._done_event = threading.Event()
        self._on_line: Callable[[str], None] | None = None
        self._timeout_s: float | None = None
        self._timeout_thread: threading.Thread | None = None

    def start(
        self,
        command: list[str],
        case_dir: Path,
        log_file: Path,
        *,
        on_line: Callable[[str], None] | None = None,
        timeout_s: float | None = None,
    ) -> None:
        """Start an OpenFOAM command asynchronously.

        Args:
            command: Command and arguments (e.g., ["icoFoam"]).
            case_dir: Working directory for the OpenFOAM case.
            log_file: Path where stdout+stderr will be written.
            on_line: Optional callback invoked for each output line (runs in
                the reader thread).
            timeout_s: Optional wall-clock timeout in seconds. When exceeded,
                the process group is terminated.
        """
        if not command:
            raise ValueError("command must not be empty")

        self._log_file_path = Path(log_file)
        self._log_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._on_line = on_line
        self._timeout_s = timeout_s
        self._case_dir = Path(case_dir)

        cmd_str = shlex.join(command)
        shell_cmd = (
            f"source {shlex.quote(str(OPENFOAM_BASHRC))} && exec {cmd_str}"
        )

        self._log_file_handle = open(
            self._log_file_path, "w", encoding="utf-8"
        )
        self._start_time = time.monotonic()
        self._process = subprocess.Popen(
            ["bash", "-c", shell_cmd],
            cwd=self._case_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
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

    def _read_output(self) -> None:
        """Reader thread: read lines from stdout, write to log, call on_line."""
        assert self._process is not None
        assert self._process.stdout is not None
        assert self._log_file_handle is not None
        try:
            for raw_line in self._process.stdout:
                line = raw_line.decode("utf-8", errors="replace")
                with self._lock:
                    self._lines.append(line)
                self._log_file_handle.write(line)  # type: ignore[union-attr]
                self._log_file_handle.flush()  # type: ignore[union-attr]
                if self._on_line is not None:
                    try:
                        self._on_line(line)
                    except Exception:
                        self._callback_errors += 1
        finally:
            self._process.wait()
            self._end_time = time.monotonic()
            self._log_file_handle.close()  # type: ignore[union-attr]
            self._done_event.set()

    def _timeout_watcher(self) -> None:
        """Timeout thread: wait for timeout_s then terminate the process."""
        assert self._timeout_s is not None
        if self._done_event.wait(timeout=self._timeout_s):
            return  # Process finished before timeout
        # Timeout reached
        self._timed_out = True
        self._terminate_process_group()

    def _terminate_process_group(self, grace_s: float = 2.0) -> None:
        """Send SIGTERM to the process group, then SIGKILL after grace period."""
        if self._process is None or self._process.poll() is not None:
            return
        try:
            pgid = os.getpgid(self._process.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        # Wait for grace period
        for _ in range(int(grace_s * 10)):
            if self._process.poll() is not None:
                return
            time.sleep(0.1)
        # Force kill
        try:
            pgid = os.getpgid(self._process.pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def is_running(self) -> bool:
        """Return True if the process is still running."""
        return not self._done_event.is_set()

    def wait(self, timeout: float | None = None) -> None:
        """Block until the process finishes.

        Args:
            timeout: Maximum time to wait in seconds. None means wait forever.
        """
        self._done_event.wait(timeout=timeout)

    def stop(self, grace_s: float = 10.0) -> None:
        """Request a clean stop of the running process.

        Sets ``stopAt writeNow`` in the case's ``system/controlDict`` (requires
        ``runTimeModifiable true``, which the generated cavity case has) so the
        solver writes the current time step and exits cleanly. If the process
        does not exit within *grace_s* seconds after the controlDict edit, it
        is terminated via SIGTERM to its process group, then SIGKILL after a
        further short grace period.

        Args:
            grace_s: Seconds to wait for clean exit after controlDict edit.
        """
        if self._process is None or self._process.poll() is not None:
            return
        self._stopped_by_user = True

        # Try clean stop via controlDict
        if self._case_dir is not None:
            from cfdgui.foam.dictfile import set_foam_entry

            control_dict = self._case_dir / "system" / "controlDict"
            if control_dict.is_file():
                try:
                    set_foam_entry(control_dict, "stopAt", "writeNow")
                except Exception:
                    pass  # Fall through to hard terminate

        # Wait for clean exit
        if self._done_event.wait(timeout=grace_s):
            return

        # Hard terminate
        self._terminate_process_group()
        self._done_event.wait(timeout=5.0)

    def result(self) -> RunResult:
        """Return the result of the completed run.

        Raises RuntimeError if the process has not finished.
        """
        if not self._done_event.is_set():
            raise RuntimeError("Process has not finished yet")
        assert self._process is not None
        assert self._log_file_path is not None
        duration = (self._end_time or time.monotonic()) - self._start_time
        return RunResult(
            exit_code=self._process.returncode,
            duration_s=duration,
            log_file=self._log_file_path,
            stopped_by_user=self._stopped_by_user,
            timed_out=self._timed_out,
            callback_errors=self._callback_errors,
        )

    @property
    def lines(self) -> list[str]:
        """Return a copy of all lines received so far."""
        with self._lock:
            return list(self._lines)
