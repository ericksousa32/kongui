# Test plan for a real Plasma session (B-3)

A script for trying KonGUI on a real Fedora KDE / Plasma session, and a template to
report the result. It exists because the automated tests never apply anything to a
real session ([`FINAL_AUDIT.md`](FINAL_AUDIT.md) §6): what they prove is that the
code behaves in a temporary home, not that Plasma ends up looking right.

The results go to [`FINAL_AUDIT.md`](FINAL_AUDIT.md) §7. Requirement B-3 changes
status only when a report has been recorded there.

## Before you start

* **Back up `~/.config`** (and `~/.local/share` if you use custom themes, icons or
  widgets) with a tool of your own. KonGUI makes a safety copy before `apply` and
  `import`, but it only covers the files the operation overwrites, and it is not a
  full backup.
* Use a virtual environment (see the README, *Installing the pre-release*).
* Run as a regular user. Note the versions below; they go in the report.

| What | How to find it |
|---|---|
| KonGUI | *About → KonGUI version* |
| Konsave engine | *About* (`2.2.0+kongui`) |
| Python, PySide6 | `python --version`, `pip show PySide6` |
| Fedora, Plasma, Qt | `cat /etc/fedora-release`, `plasmashell --version`, `qmake6 --version` |
| Session | `echo $XDG_SESSION_TYPE` (`wayland` or `x11`) |
| Scaling | *System Settings → Display*, for example 100%, 125%, 150% |

## Checks

Mark each one *ok*, *problem* (describe it) or *not tested*.

### 1. Start and look

1. `kongui --demo`: the window opens, the six pages open (Dashboard, Profiles,
   Transfer, Settings, `conf.yaml`, About), nothing is written to `~/.config/konsave`.
2. `kongui`: the real profiles are listed (or an empty state if you have none).
3. Switch the Plasma color scheme (light ↔ dark) with the app open: the interface
   follows it and stays readable.
4. Fractional scaling (125% / 150%): no cut-off text or overlapping controls.
5. Language: with the system in Portuguese the interface is in Portuguese; *Settings
   → Language* switches it live.

### 2. Save and apply (the part no automated test can cover)

1. **Save profile** with a new name. The card shows its sections.
2. Change something visible (a wallpaper, the color scheme, a panel setting).
3. **Apply** the profile. Confirm the dialog. Check:
   * a safety copy appeared in *Settings → Safety copies → Manage…*;
   * the change you made is reverted after logging out and in again (note whether
     parts of it were applied without that);
   * nothing outside the profile changed.
4. **Restore** the safety copy and confirm you are back to the state before the apply.
5. Apply while a Plasma setting window is open: note any surprise.

### 3. Export and import

1. Export a profile to a `.knsv` and check the file is created where you chose.
2. Import it back under another name (and again with a name that already exists (note what
   KonGUI asks and what happens).
3. Drag a `.knsv` from Dolphin onto the Transfer page, on **Wayland** and on **X11**
   if you can try both.
4. Import with the destination folders of the `export` section missing: the message
   should say what is wrong (this is Konsave's rule, not a KonGUI bug).

### 4. The `conf.yaml` editor

1. Open *Edit .YAML*, add a group, save. Check that `conf.yaml.bak-*` appeared next to
   the file.
2. Save a profile and confirm the new group is in its sections.
3. Type invalid YAML and see that the editor refuses to save it and says why.

### 5. Two things at once

1. Open two KonGUI windows and start an operation in each: the second must wait
   ("waiting for another operation") and be cancellable.
2. Run `konsave -l` in a terminal during an operation: it must wait, not fail.

### 6. Environment

1. **SELinux** (enforcing, the Fedora default): look for denials after the checks
   above (`sudo ausearch -m avc -ts recent`) and report any that mention KonGUI or
   Python.
2. **Flatpak**: if you use Flatpak apps (for example a Flatpak browser or editor),
   note whether their settings under `~/.var/app` are part of what you save. They are
   not in the default `conf.yaml`.
3. **Quit** the window while an operation is running: note what happens.

## Report template

Copy this into an issue (or send it to the owner) and fill it in.

```
KonGUI version:
Fedora / Plasma / Qt:
Session (Wayland/X11) and scaling:
Python / PySide6:
Installed from (wheel of a release / clone):

1. Start and look:            ok / problem / not tested
2. Save and apply:            ok / problem / not tested
3. Export and import:         ok / problem / not tested
   drag and drop:             Wayland ok/problem/not tested; X11 ok/problem/not tested
4. conf.yaml editor:          ok / problem / not tested
5. Two things at once:        ok / problem / not tested
6. SELinux / Flatpak / quit:  ok / problem / not tested

Problems (one per line: what you did, what you saw, what you expected):

Was a safety copy made before apply/import?   yes / no
Could you go back from it?                    yes / no / not tried
```

## What counts as a blocker for the alpha

A problem that **loses or corrupts the user's configuration**, an apply or import that
changes files outside the profile, a safety copy that is missing or cannot be
restored, or a crash on start. Cosmetic problems and missing features are recorded
but do not block an alpha ([`LIMITATIONS.md`](LIMITATIONS.md)).
