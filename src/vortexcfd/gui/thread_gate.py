"""Signals emitted from worker threads, and their end (D-164).

A worker thread that emits a Qt signal of a QObject while the GUI thread deletes that QObject (its window was
closed and is being deleted) writes into freed memory; the heap is corrupted and the process crashes later, at
an unrelated free (the offscreen test-suite crashes in widget teardown, QUESTIONS 82). Every signal a worker
thread emits therefore goes through a ``ThreadGate``; the owner closes the gate before the QObject can be deleted.
``close`` waits for an emission in progress and stops every later one, so after it returns no thread touches the
QObject. Emitting only queues an event for the GUI thread (the receivers live there), so the lock is held briefly.
"""

import threading


class ThreadGate:
    def __init__(self) -> None:
        self._lock = threading.RLock()  # reentrant: a slot run directly by an emission may close the gate
        self._open = True

    @property
    def is_open(self) -> bool:
        return self._open

    def emit(self, signal, *args) -> bool:
        """Emit ``signal`` (a bound signal of the gate's owner) with ``args`` unless the gate is closed; False when
        it was not emitted."""
        with self._lock:
            if not self._open:
                return False
            try:
                signal.emit(*args)
            except RuntimeError:  # the owner's C++ object is already gone
                self._open = False
                return False
            return True

    def emitter(self, signal):
        """A callback for a worker thread: ``emitter(sig)(*args)`` is ``emit(sig, *args)``."""
        return lambda *args: self.emit(signal, *args)

    def close(self) -> None:
        """No emission after this returns (one in progress is waited for)."""
        with self._lock:
            self._open = False
