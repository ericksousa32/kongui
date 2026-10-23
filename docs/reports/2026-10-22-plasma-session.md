# Real Plasma session report: 2026-10-22 (B-3)

First report of KonGUI in a real Fedora KDE session, made by the project owner with
the template of [`../PLASMA_TEST_PLAN.md`](../PLASMA_TEST_PLAN.md). It was a **quick
test**: every feature tried worked, but more thorough testing is needed to find
possible bugs, and some checks were not done. The summary and what it changes are in
[`../FINAL_AUDIT.md`](../FINAL_AUDIT.md) §7.

## Report (as received)

```
KonGUI version: dev
Fedora / Plasma / Qt: 44 / 6.7.5 / 6.11.2
Session (Wayland/X11) and scaling: Wayland
Python / PySide6: Python 3.14.8 / python3-pyside6-6.11.2-1.fc44.x86_64
Installed from (wheel of a release / clone): dev

1. Start and look:            ok, but needs minor adjustments to the layout and alignment of the text.
2. Save and apply:            ok
3. Export and import:         ok
   drag and drop:             Wayland ok; X11 not tested
4. conf.yaml by hand:         ok
5. Two things at once:        ok
6. SELinux / Flatpak / quit:  not tested

Problems (one per line: what you did, what you saw, what you expected): n/a

Was a safety copy made before apply/import?   yes
Could you go back from it?                    yes
```

## Notes

* Version `dev` means the code ran from a clone that was never installed as a
  package (before the first tag), so it is not tied to a commit here; it was the
  state of `dev` on 2026-10-22 or close to it.
* PySide6 came from Fedora's own package (6.11.2, with Qt 6.11.2) on Python 3.14.
  That PySide6 release is not in the automated test matrix (6.8, 6.9 and 6.12 are);
  it worked here.
* No blocker in the sense of the test plan: nothing lost or corrupted the
  configuration, apply and import made a safety copy, and going back from it worked.
