# Cross-process lock

Two programs working on the same files at the same time (two KonGUI instances, or
KonGUI and the `konsave` command) could corrupt profiles, overwrite `conf.yaml` or
mix safety copies. Since this stage, every operation that uses Konsave data goes
through a lock provided by the operating system itself. The changes to the original
code are listed in [`KONSAVE_PATCHES.md`](KONSAVE_PATCHES.md).

Note on interface texts: the interface is available in English and Brazilian
Portuguese. Labels and messages are quoted below as they appear in the Portuguese
interface, with an English gloss in parentheses where needed.

## 1. How it works

* Mechanism: Linux `fcntl.flock()` on a fixed file,
  **`~/.config/konsave/.kongui.lock`** (inside Konsave's data folder, so that every
  program that sees the same profiles sees the same lock; it is not in
  `XDG_RUNTIME_DIR`, which changes between sessions, `su` and `ssh`).
* It does **not** use a PID file, a temporary file or window detection. The system
  releases the lock by itself when the process ends, even if killed by `kill -9`.
* The lock file is **never deleted or recreated** (deleting it would allow two
  owners). It has permission `0600`, is opened without following symbolic links and
  must be a regular file owned by the user; otherwise the operation fails with a
  clear error.
* Two modes: **exclusive** (changes data) and **shared** (only reads; several
  readers at once, but never together with a writer).
* The descriptor stays open during the whole protected operation and is closed at
  the end, also on exception. It is not inherited by child processes.
* Waiting is done by non-blocking attempts (10 ms growing to 100 ms), which allows a
  **timeout** and **cooperative cancellation** (`threading.Event`).
* Within the same process the lock is **re-entrant per thread** (a high-level
  function may call another). Asking for exclusive while holding shared is an error
  (`LockUsageError`), because it would lock itself. The order is always: file lock
  first, then `ENGINE_LOCK` (the process's `RLock`); there is no reverse order.
* The file stores, for messages only, `{pid, operation, since}` of whoever holds the
  exclusive lock. It is **information**, not proof of ownership: if the PID no
  longer exists it is ignored, and the system (`flock`) always decides.

## 2. What is protected

| Operation | Lock |
|---|---|
| save, replace, apply, remove, import, wipe all | exclusive |
| restore and delete a safety copy | exclusive |
| create the default `conf.yaml` | exclusive |
| list profiles, read a profile, export, list copies | shared |
| read a `conf.yaml` (KonGUI never writes one; the user edits it by hand) | the lock of the operation that reads it |
| `konsave --version`, `--help` | no lock |

The lock is **not** held while the user decides in a dialog: it only exists inside
the call that performs the operation.

## 3. Where it is in the code

| Part | Location |
|---|---|
| Mechanism (no dependencies) | `konsave/lock.py` |
| Original command line | `konsave/__main__.py` (`command_lock`) |
| KonGUI layer | `kongui/core/lock.py` (`EngineLock`, `LockPolicy`, `guarded`) |
| Services | `@guarded(...)` on `ProfileService` and `ConfigService`; `KonsaveEngine.call` locks the original functions that change data (`CALL_LOCK_MODES`) |
| Interface messages | `kongui/gui/messages.py` (`describe_error`) |

The interface **does not use a subprocess** to talk to Konsave, so there is no
double acquisition; `CliRunner` only runs diagnostics and nothing that changes data.

## 4. How a conflict appears

**Command line**

```
Konsave: another Konsave operation is running (apply, pid 1234); waiting up to 30 s (Ctrl+C to give up)...
```

If the time runs out: `Konsave: … Nothing was changed.` and exit status **75**
(`EX_TEMPFAIL`). Unusable lock: status 1. Ctrl+C: 130. The wait time is set by
`KONSAVE_LOCK_TIMEOUT` (seconds; `0` = do not wait; negative or `inf` = no limit).

**Graphical interface**

The operation runs in the background (the window does not freeze) and, if another
process holds the lock, it **waits** instead of failing:

* a strip appears below the top bar: "Aguardando outra operação do Konsave…"
  (Waiting for another Konsave operation…), with the explanation and, when known,
  the (unverified) hint of which operation/process holds the lock;
* the strip's **Cancelar espera** (Cancel wait) button interrupts only the wait:
  nothing is changed, the other operation is not touched and the notice "Espera
  cancelada" (Wait cancelled) appears. After that the window returns to normal and
  the same action can be repeated;
* while waiting, the operation counts as "in progress": all buttons that change
  data are disabled (as with any operation), the card of the profile involved shows
  "Aguardando outra operação…", and closing the window is refused with the notice
  "Cancele a espera ou aguarde…" (Cancel the wait or wait…);
* if the other operation finishes, ours starts by itself, the strip disappears and
  the result appears as usual;
* if the wait exceeds the limit (`LockPolicy.timeout`, 30 s), the operation ends
  with "A outra operação do Konsave … não terminou a tempo. Nada foi alterado"
  (the other Konsave operation … did not finish in time. Nothing was changed);
* an unusable lock file (folder without permission, etc.) is not a wait: the error
  appears at once, naming the file.

How it works inside: the controller (`ProfileController`) gives the backend a
cancellation `threading.Event` and an `on_wait` callback (`configure_lock_wait`);
the callback runs on the worker thread and reaches the window through a Qt signal;
`cancel_wait()` only raises the event. When the operation fails because of the lock,
the profile list is **not** read again (nothing ran, and reading it would wait for
the same lock). The user's confirmation (dialog) happens **before** the operation,
so the lock is never held while they decide. Demo mode simulates another process
with `FakeBackend.start_other()` / `finish_other()`.

Interface limitations: the window does not watch the lock by itself and only finds
out about the conflict when the user triggers an action; background reads
(`inspect_archive`, `probe_export`, which use the same worker thread) queue up
behind an operation that is waiting.

## 5. Limitations

* Only programs that use the lock are protected. **External tools** (Plasma itself,
  editors, another configuration manager) ignore the lock.
* Whoever calls `konsave.funcs` directly as a library, without going through
  `__main__` or KonGUI, is not protected.
* There is no fair queue (FIFO): when the lock is released, whoever tries first
  gets it.
* On NFS `flock` is emulated; it is not supported as a production setup.
* Fail closed: if the lock file cannot be opened, the commands that use the lock
  (including `--list`) refuse instead of running unprotected.
* The CLI exits with 75 on conflict, whereas the original Konsave always exits
  with 0.
* `conf.yaml` is edited by hand, in a text editor that does not use the lock: an
  operation that reads it while it is being saved may see an incomplete file and
  fail with Konsave's reason (run it again).

## 6. Tests

`tests.test_locking` uses **real processes** and the real `flock`, in temporary
folders and without touching the session: two processes competing; exclusive ×
shared; simultaneous readers and a read during a write; a second operation waiting
for the first; timeout and cancellation; an exception inside the operation; a
process killed with `SIGKILL`; a stale owner record ignored; a folder without
permission, or a directory or link in place of the file; CLI × CLI, service × CLI
in both directions, two "KonGUI" instances; profile list read again after the
wait; simultaneous first run; exit statuses 75/1/130; re-entrancy and the ban on
upgrading the lock; lock-free commands (`--version`, `--help`) never wait;
interface texts.
`tests.test_gui_lock_wait` covers the interface: the wait strip with the owner
hint, a window that stays responsive during the wait (the Qt timer keeps firing),
locked buttons, cancellation (nothing changed, next operation normal), the end of
the wait when the other operation finishes, timeout, closing the window, the "Espera
cancelada" notice, a background read that does not look like a wait, and the same
flows with the real services against a helper process that holds the real `flock`.
The older tests (`tests.test_profile_service_integration`, `tests.test_gui_startup`)
were adjusted only to accept the `.kongui.lock` file and the `konsave.lock` module.
