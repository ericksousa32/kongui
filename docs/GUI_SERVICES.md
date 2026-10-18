# Interface wired to the services

The window no longer uses only fictitious data: the profile operations go through
KonGUI's `ProfileService` (and, through it, the original Konsave). The code in
`konsave/` was **not changed**, except for the cross-process lock described in
[`KONSAVE_PATCHES.md`](KONSAVE_PATCHES.md).

Note on interface texts: the interface is available in English and Brazilian
Portuguese. Labels and messages are quoted below as they appear in the Portuguese
interface, with an English gloss in parentheses where needed.

## 1. How to use

```bash
python3 -m kongui.gui           # real profiles of the current user
python3 -m kongui.gui --demo    # fictitious data; nothing is written or applied
```

The program refuses to run as root and warns if Konsave cannot be loaded.
Import and export are described in §4.

## 2. Architecture

```
Page ──► ProfileActions (dialogs) ──► ProfileController ──► Executor (thread)
  ▲                                          │                     │
  └────────── ProfileStore ◄─────────────────┘            ProfileBackend
                                                  ServiceBackend │ FakeBackend
```

* `ProfileBackend` (`backend.py`) is what the interface needs. `ServiceBackend`
  calls `ProfileService`; `FakeBackend` keeps profiles in memory (demo mode and
  tests). The methods block and never touch Qt objects.
* `ProfileController` (`controller.py`) runs **one operation at a time**. Requests
  made during an operation are refused (the GUI says "Aguarde", wait). After each
  operation, even if it fails, the list is read again and published to the
  `ProfileStore`, and an `Outcome` is emitted.
* `tasks.py`: `ThreadExecutor` runs the work in a thread and hands the result back
  to the interface thread through a signal; the interface does not freeze.
* **Nothing that touches the disk runs on the interface thread**: reads
  (`conf.yaml`, backups, `.knsv` inspection) go through `controller.background`,
  and so does the check of the export folder (`probe_export`). The window **does
  not close** while an operation runs (notice "Operação em andamento", operation
  in progress): Konsave cannot be interrupted, and closing would leave the process
  orphaned.
* `OutcomeNotifier` (`actions.py`) shows the notice (errors stay until closed) and
  records the activity.
* `messages.py` translates results and exceptions to the language in use. Unknown exceptions
  appear with their type, so that a bug does not stay hidden.

## 3. The six operations

| Operation | Service | Loading | Confirmation |
|---|---|---|---|
| List | `list_profiles` | "Carregando…" (Loading…) on the page and panel; thin bar under the top bar | — |
| Save | `ConfigService.ensure_default_config` + `save` | buttons locked, busy bar | — (name validated first) |
| Overwrite | `ProfileService.replace` | card shows "Sobrescrevendo…" | destructive dialog |
| Apply | `apply` | card shows "Aplicando…" | destructive dialog |
| Remove | `remove` | card shows "Removendo…" | destructive dialog |
| Clear all | `wipe_all` | buttons locked | destructive dialog **and** typing `APAGAR` |
| Export | `ProfileService.export` | busy bar, button locked | only to replace a file (see §4) |
| Import | `ProfileService.import_profile` | background check, then busy bar | always |

Each error appears as a persistent notice with the cause; a failure to list shows a
strip with "Tentar novamente" (Try again). The lower layers also require
`confirmed=True` ("truthy" values such as `1` are refused).

### Why `replace` exists (the only change outside the GUI)

`konsave save -f` **merges** the old profile instead of replacing it: files that no
longer exist stay in the profile. For a real "Sobrescrever" (Overwrite),
`ProfileService.replace` was added, without touching Konsave: it saves under a
temporary name (`.kongui-…`), checks the result and swaps with `rename`, rolling
back if anything fails. Entries with that prefix are never listed.

### Operations on `conf.yaml`

`ProfileBackend` also exposes `load_config`, `check_config`, `save_config`,
`list_config_backups`, `read_config_backup` and `restore_config` (see
[`GUI_CONFIG.md`](GUI_CONFIG.md)). Reads run in the background without counting as
an operation; `save_config` and `restore_config` use the same cycle as the others
(busy bar, success or error notice) and do not reload the profile list.

## 4. Import and export

Format: Konsave's **original** `.knsv` (a zip with `conf.yaml`, `save/` and
`export/`). The GUI creates no new format; the tests exchange files with the
original `python -m konsave` in both directions.

### CLI options and how they appear

| Original CLI | In the interface | Real behavior |
|---|---|---|
| `-e PROFILE` | "Perfil" list | the profile must exist and have a valid `conf.yaml` |
| `-d FOLDER` | "Pasta de destino" (Destination folder) + **Escolher…** (Choose…) | the original uses the current folder; here the default is `~/Downloads`. The folder must exist and accept writing (checked first, with a clear message). `~` means the engine's home |
| `-n NAME` | "Nome do arquivo (sem extensão)" (File name, without extension) | starts equal to the profile; same core name rules (no `/`, `.`/`..`, leading `-`, `.knsv`/`.zip`) |
| `-f` | "O arquivo já existe" (The file already exists) dialog | see below |
| `-i FILE` | drop area / **Escolher arquivo** (Choose file) | `.knsv` only; the file is checked (read-only) as soon as it is chosen |
| (none) | "Nome do perfil importado" (Imported profile name) | the original uses the file name; see "Rename" |
| (none) | "Aplicar o perfil depois de importar" (Apply the profile after importing) | a separate second step: if it fails, the profile stays imported and a warning explains |

### Conflict on export (semantics of `-f`)

Without `-f` the original **does not ask**: it appends date and time to the name.
With `-f` it replaces. The original's `force` also deletes a folder named like the
file, which is why the GUI never passes it for folders. There is no selector: when
the destination already exists, the GUI **always asks**:

| Situation | "O arquivo já existe" dialog |
|---|---|
| a `.knsv` exists | **Replace** (regular file only), **Use unique name** (`name-2.knsv`, `name-3.knsv`…) or Cancel |
| a folder, `.zip` or link with that name exists | only **Use unique name** or Cancel (the original would delete the folder) |

When nothing exists, the export runs with the `error` policy: if someone creates the
file along the way, it is **not** overwritten. Known difference: the original's
unique name is `name_fDD-MM-YYYY:HH-MM-SS`; the core's is `name-2`.

### Import

* **Always confirms**: the original writes the archive's `export` section straight
  into the system (for example `~/.local/share/icons`), overwriting (beforehand,
  the files that would be overwritten are copied: see §7). The dialog lists the
  sections that will be written.
* Never replaces a profile: if the name already exists, the form refuses (the
  original also refuses).
* `ProfileService.inspect_archive` (new, read-only) performs the same checks as
  the import — readable zip, safe member names, `conf.yaml` and `save/` present,
  valid configuration and destinations inside the home — and shows name, size and
  sections before anything is written. A missing file, a non-zip, one without
  `conf.yaml`, with unsafe paths or without read permission appears as an error in
  the form.
* Destinations **outside the home** are still refused (`allow_outside_home` is not
  exposed in the interface).
* **Rename**: the original names the profile after the file. To use another name,
  the *same* file is copied to a private temporary folder under the new name and
  imported from there; the copy is deleted at the end, even on error, and the
  original is not touched. It is not a new format.

### Profile details

The save dialog asks for an optional description (500 characters at most). *Edit
details…* in the card menu changes it later; cancelling changes nothing and an empty
text clears it. If a profile is saved but its description cannot be written, the
notice is a **warning** (not a success) that says so; a failed edit is an error and
keeps the previous text. The description is shown as plain text.

### Limits and free space

Before the engine is called, an import refuses a file above 512 MiB, an archive with
more than 10,000 entries or one that really expands to more than 2 GiB (counted
while decompressing, stopping at the limit), and tells a corrupted archive from a
foreign file. Import and export also check free space (`shutil.disk_usage`, with a
64 MiB margin) and stop with nothing changed. A failed export never replaces the
previous one. Details and constants: [`INTEGRATION.md`](INTEGRATION.md) §10.

### Errors

Permission denied, a missing file or folder and other `OSError`s become messages in
the language in use (and are not logged as bugs). Export failures stay on screen until closed and
the form stays filled in.

## 5. Tests

No test applies a profile to the real session: they use `FakeBackend` or a
temporary `$HOME`, and the tests with files refuse to run as root.

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_gui_operations tests.test_gui_real_backend tests.test_gui_support tests.test_gui_transfer tests.test_gui_transfer_roundtrip tests.test_gui_config tests.test_config_editor -v
```

`tests.test_gui_transfer_roundtrip` exports in one home and imports in another with
the real Konsave, compares the profile byte by byte and repeats it with the original
CLI.

## 6. Known limitations

* Apply is not atomic: if it fails halfway, part of the files has already been
  swapped (the notice shows Konsave's errors).
* Import writes the archive's `export` section **before** anything else; if Konsave
  fails afterwards, the profile is undone, but those already-written files do not
  come back on their own: restore the safety copy (§7).
* "Active" is only the last profile applied from this interface (`last_applied`);
  Konsave does not record it.
* Konsave stores no description: KonGUI keeps one in a small file inside the profile
  folder (see [`INTEGRATION.md`](INTEGRATION.md) §11). It does not travel in the
  `.knsv` (an imported profile starts without one), and it is lost if the profile
  folder is removed or replaced by something that does not copy it.
* The sections shown on a card are the `save` groups of the profile's `conf.yaml`
  that hold files. Choosing what to include when saving is not offered: edit the
  `conf.yaml` (*Edit .YAML*) instead; the steps are in
  [`GUI_CONFIG.md`](GUI_CONFIG.md) §7. In demo mode the save dialog still shows the
  fictitious check boxes.
* No cancellation or partial progress; only "busy". Exporting or importing a large
  profile can take long and blocks other operations.
* The complete list of limitations and the decisions behind them is in
  [`LIMITATIONS.md`](LIMITATIONS.md).
* Safety copies are never deleted automatically and their number is not limited
  (project decision; delete them in *Settings → Safety copies → Manage…*).
* The limits and the free-space estimates are simple constants and approximations
  (the check and the real operation are not atomic: another program can still fill
  the disk in between; a real `ENOSPC` is then reported and cleaned up). The
  decompression pass reads the archive once more before importing, which costs time
  for large archives. The export section is read from the live system, so its size
  can change between the estimate and the copy.
* The `.knsv` is neither signed nor encrypted, and its `conf.yaml` decides where
  the files go: the GUI only accepts destinations inside the home, but import only
  archives from trusted sources.
* Export copies the current **global** `conf.yaml` into the `.knsv`, but assembles
  `save/` and `export/` from the groups of the **profile's** `conf.yaml` (a Konsave
  limitation). If they differ, the archive contradicts itself: a new group prevents
  applying the imported profile; a removed group is ignored without a warning. The
  GUI warns on export and when inspecting the archive, but does **not rewrite** the
  archive's `conf.yaml` (that would change Konsave's output; project decision).
* The executable bit and file metadata do not survive the export → import cycle
  (a Konsave limitation).
* `replace` uses `rename` (same file system) and only leaves a `.kongui-*` leftover
  if the process dies halfway.
* Two KonGUI instances (or `konsave` on the command line) at the same time are
  serialized by the cross-process lock; the interface shows the wait and lets you
  cancel it (see [`CONCURRENCY.md`](CONCURRENCY.md) §4).
* The engine redirects `stdout` globally during each call.
* Editing `conf.yaml` is described in [`GUI_CONFIG.md`](GUI_CONFIG.md).
* Testing in a real Plasma session is in progress.

## 7. Safety copies (RN-01)

Before **applying** or **importing**, the service copies the files that would be
overwritten (details in [`INTEGRATION.md`](INTEGRATION.md) §9). In the interface:

* the apply/import notices state the copy identifier ("Cópia de segurança
  guardada…", safety copy kept…), and the confirmation texts no longer say "no
  backup";
* **Configurações → Cópias de segurança → Gerenciar…** (Settings → Safety copies →
  Manage…) opens the list (date, operation, profile, files replaced/created, size,
  newest first);
* **Restaurar** (Restore) asks for confirmation (destructive), keeps the current
  state as a new copy and puts the files back; **Apagar** (Delete) asks for
  confirmation. The buttons stay locked while another operation runs, the list is
  read in the background and read again after each restore or delete;
* if the copy cannot be made, the error appears and **nothing is applied or
  imported**;
* no copy is deleted automatically; the copy of an `import` does not undo the
  imported profile;
* demo mode: fictitious copies, nothing is written.

Tests: `tests.test_snapshot` (core, real Konsave in a temporary `$HOME`) and
`tests.test_gui_backups` (dialog, controller, messages and end to end).
