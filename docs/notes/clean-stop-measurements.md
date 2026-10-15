# OpenFOAM Solver Clean Stop Mechanism

## Question: Earliest Reliable Clean Stop & Mechanism

### 1. Earliest Wall-Clock Time for Clean Stop
- **Baseline (Default OpenFOAM settings)**:
  - **Earliest reliable clean stop**: **~5 to 6 seconds** after solver launch.
  - **Reason**: OpenFOAM's default configuration (`/usr/lib/openfoam/openfoam2606/etc/controlDict`, line 94) sets `fileModificationSkew 5;`. In `fileMonitor.C`, OpenFOAM checks `newTime > oldTime + fileModificationSkew`. Any modification to `system/controlDict` within the first 5 seconds after startup has an `mtime` that does not exceed `start_mtime + 5s`. OpenFOAM treats the file as `UNMODIFIED`. Because no further writes occur, OpenFOAM never re-checks the file, and the solver runs to natural completion (`end_time = 20.0`, ~10.7 s total wall-clock runtime). At 4.0 s delay, runs are on the boundary and nondeterministic (1 out of 3 runs missed the threshold).
- **Alternative (a) (`fileModificationSkew 0;`)**:
  - **Earliest reliable clean stop**: **Immediate (< 1.0 s)** after the first time step begins.
  - Measured exit latency after file edit: **~0.011 s** at both 1.0 s and 3.0 s delays.
- **Alternative (b) (`stopAtWriteNowSignal 10;` + `SIGUSR1`)**:
  - **Earliest reliable clean stop**: **Immediate (< 1.0 s)** after the first time step begins.
  - Measured exit latency after signal: **~0.008 – 0.012 s** at both 1.0 s and 3.0 s delays.

---

### 2. Mechanisms Investigated

#### Baseline: File Modification without Skew Override
- `FoamRun.stop()` edits `system/controlDict` to set `stopAt writeNow;`.
- Blocked by default 5 s skew check in OpenFOAM's `fileMonitor`.

#### Alternative (a): File-Based with `fileModificationSkew 0`
- Case's `system/controlDict` includes:
  ```openfoam
  OptimisationSwitches
  {
      fileModificationSkew 0;
  }
  ```
- Handled at startup by `TimeIO.C` (`debug::optimisationObjects().setValues(*localDict, true)`).
- `FoamRun.stop()` writes `stopAt writeNow;` to `system/controlDict`.
- OpenFOAM's `fileMonitor` detects the change on the next time step, writes fields, and exits cleanly with exit code 0.

#### Alternative (b): POSIX Signal-Based (`stopAtWriteNowSignal`)
- OpenFOAM source: `/usr/lib/openfoam/openfoam2606/src/OSspecific/POSIX/signals/sigStopAtWriteNow.cxx`.
- `/usr/lib/openfoam/openfoam2606/etc/controlDict` line 245 defines `stopAtWriteNowSignal -1;` (disabled by default).
- Case's `system/controlDict` enables it:
  ```openfoam
  OptimisationSwitches
  {
      stopAtWriteNowSignal 10; // SIGUSR1
  }
  ```
- When `icoFoam` starts, `sigStopAtWriteNow::set` installs a signal handler for `SIGUSR1` (signal 10).
- When the runner sends `SIGUSR1` (`os.kill(pid, signal.SIGUSR1)`), the handler calls `runTimePtr_->stopAt(Time::saWriteNow)`.
- OpenFOAM logs:
  `sigStopAtWriteNow : setting up write and stop at end of the next iteration`
- The solver finishes its current iteration, writes the current time step (including `U` and `p`), and exits cleanly with exit code 0.

---

### 3. Side Effects Noticed

| Aspect | Alternative (a): `fileModificationSkew 0` | Alternative (b): `stopAtWriteNowSignal 10` |
| :--- | :--- | :--- |
| **On-Disk File Mutation** | Modifies `system/controlDict` on disk (`stopAt writeNow;`). If the case is re-run without manual cleanup, it halts immediately at step 1. | **None**. `system/controlDict` remains unmodified on disk. The case can be resumed or re-run cleanly without file cleanup. |
| **Filesystem Dependencies** | Relies on `mtime` granularity and filesystem notification semantics (can be fragile across network/NFS mounts). | None. Pure POSIX IPC signal. |
| **Log Output** | Normal timestep write. No indication in log that stop was requested by user. | Explicitly logs: `sigStopAtWriteNow : setting up write and stop at end of the next iteration`. |
| **Portability** | Works anywhere file modification is supported. | Standard POSIX (Linux/macOS). OpenFOAM also has `OSspecific/MSwindows/signals/sigStopAtWriteNow.cxx` for Windows builds. |

---

### 4. Recommendation

**Adopt Alternative (b) (Signal-Based Stop via `stopAtWriteNowSignal 10`) as the primary stop mechanism, with fallback to file-based stop.**

**Reasons**:
1. **Case Integrity**: Alternative (b) does not mutate `system/controlDict` on disk. An interactive GUI stop should stop the execution without corrupting or altering the case's saved configuration parameters.
2. **Speed and Reliability**: Signals are delivered immediately with zero filesystem polling or timestamp skew issues. In all test runs, exit latency was under 12 ms, cleanly writing both `U` and `p`.
3. **Designed for Process Managers**: OpenFOAM explicitly provides `stopAtWriteNowSignal` and `writeNowSignal` in its POSIX OS-specific layer specifically for process supervision.

**Proposed Implementation Strategy for Future Tasks**:
1. In case generators (`case_writer` / reference cases): emit `OptimisationSwitches { stopAtWriteNowSignal 10; }` into generated `system/controlDict` files.
2. In `FoamRun.stop(grace_s)`:
   - Send `SIGUSR1` to the solver process (or process group).
   - If the process terminates within `grace_s`, return cleanly.
   - If `SIGUSR1` is unsupported or the process does not terminate within `grace_s`, attempt the file-based fallback (`set_foam_entry(controlDict, "stopAt", "writeNow")`), and finally hard terminate (`SIGTERM`/`SIGKILL`).
