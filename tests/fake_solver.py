"""A fake process runner with FoamRun's interface (start/wait/result/request_stop/is_running).

It plays a list of log lines from its own thread (like FoamRun's reader thread) and ends with a
chosen exit code. With ``hold=True`` it keeps running after the lines until a stop is requested
(it then plays ``stop_lines`` and exits 0, as a clean SIGUSR1 stop does) or ``release(lines)`` is
called (it then plays ``lines`` and exits with ``exit_code``, as a run that ends by itself);
``push(lines)`` plays more lines while it holds.
"""

import threading
from pathlib import Path

from vortexcfd.foam.runner import RunResult


def iteration(n: int, p: float = 0.1, u: float = 0.01, k: float = 0.001, omega: float = 0.002) -> list[str]:
    """The lines of one simpleFoam iteration (residual format of the v2606 log)."""
    return [
        f"Time = {n}\n",
        "\n",
        f"smoothSolver:  Solving for Ux, Initial residual = {u}, Final residual = {u / 10}, No Iterations 1\n",
        f"smoothSolver:  Solving for Uy, Initial residual = {u * 2}, Final residual = {u / 5}, No Iterations 1\n",
        f"smoothSolver:  Solving for Uz, Initial residual = {u * 3}, Final residual = {u / 3}, No Iterations 1\n",
        f"GAMG:  Solving for p, Initial residual = {p}, Final residual = {p / 100}, No Iterations 3\n",
        "time step continuity errors : sum local = 1e-05, global = 1e-07, cumulative = 1e-07\n",
        f"smoothSolver:  Solving for omega, Initial residual = {omega}, Final residual = {omega / 10}, No Iterations 1\n",
        f"smoothSolver:  Solving for k, Initial residual = {k}, Final residual = {k / 10}, No Iterations 1\n",
        f"ExecutionTime = {n * 0.1:.2f} s  ClockTime = {n} s\n",
        "\n",
    ]


CRASH_BLOCK = [
    "#0  Foam::error::printStack(Foam::Ostream&) at ??:?\n",
    "[stack trace]\n",
    "=============\n",
    "#1  Foam::sigFpe::sigHandler(int) at ??:?\n",
    "#2  ? in /lib/x86_64-linux-gnu/libc.so.6\n",
    "=============\n",
]


class FakeRunner:
    instances: list["FakeRunner"] = []

    def __init__(self, lines: list[str], exit_code: int = 0, hold: bool = False,
                 stop_lines: list[str] | None = None) -> None:
        self.lines, self.exit_code, self.hold = list(lines), exit_code, hold
        self.stop_lines = stop_lines if stop_lines is not None else ["End\n"]
        self.command = self.case_dir = self.log_file = None
        self.clean_stop = None
        self.stop_requested = False
        self._stop = threading.Event()
        self._release = threading.Event()
        self._release_lines: list[str] = []
        self._pushed: list[list[str]] = []
        self._push_lock = threading.Lock()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        FakeRunner.instances.append(self)

    def start(self, command, case_dir, log_file, *, on_line=None, timeout_s=None, clean_stop=False,
              keep_last_lines=None) -> None:
        self.command, self.case_dir, self.log_file = command, Path(case_dir), Path(log_file)
        self.clean_stop, self.on_line = clean_stop, on_line
        self._thread = threading.Thread(target=self._play, daemon=True)
        self._thread.start()

    def _emit(self, lines: list[str], log) -> None:
        for line in lines:
            log.write(line)
            if self.on_line is not None:
                self.on_line(line)

    def _play(self) -> None:
        with open(self.log_file, "w", encoding="utf-8") as log:
            self._emit(self.lines, log)
            if self.hold:
                while not (self._stop.is_set() or self._release.is_set()):
                    with self._push_lock:
                        pushed, self._pushed = self._pushed, []
                    for lines in pushed:
                        self._emit(lines, log)
                    self._stop.wait(0.01)
                if self._stop.is_set():
                    self._emit(self.stop_lines, log)
                    self.exit_code = 0
                else:
                    self._emit(self._release_lines, log)
        self._done.set()

    def push(self, lines: list[str]) -> None:
        with self._push_lock:
            self._pushed.append(list(lines))

    def release(self, lines: list[str] | None = None) -> None:
        self._release_lines = list(lines or [])
        self._release.set()

    def request_stop(self, grace_s: float = 10.0) -> bool:
        self.stop_requested = True
        self._stop.set()
        return True

    def is_running(self) -> bool:
        return self._thread is not None and not self._done.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def result(self) -> RunResult:
        return RunResult(exit_code=self.exit_code, duration_s=0.1, log_file=self.log_file,
                         stopped_by_user=self.stop_requested, stop_requested=self.stop_requested,
                         stop_mode="clean" if self.stop_requested else "none")
