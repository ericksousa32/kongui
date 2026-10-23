---
name: Plasma test report
about: Tell how KonGUI behaved in your real KDE Plasma session
title: '[Test report] '
labels: 'test report'
---

> Thank you for testing. The steps are in
> [`docs/PLASMA_TEST_PLAN.md`](../../docs/PLASMA_TEST_PLAN.md). **Back up `~/.config`
> first.** Mark only what you really tried; "not tested" is a useful answer. Checks
> nobody has reported yet: drag and drop on X11, SELinux, Flatpak, quitting during an
> operation.

```
KonGUI version:
Distribution / Plasma / Qt:
Session (Wayland/X11) and scaling:
Python / PySide6:
Installed from (wheel of a release / clone):

1. Start and look:            ok / problem / not tested
2. Save and apply:            ok / problem / not tested
3. Export and import:         ok / problem / not tested
   drag and drop:             Wayland ok/problem/not tested; X11 ok/problem/not tested
4. conf.yaml by hand:         ok / problem / not tested
5. Two things at once:        ok / problem / not tested
6. SELinux / Flatpak / quit:  ok / problem / not tested

Problems (one per line: what you did, what you saw, what you expected):

Was a safety copy made before apply/import?   yes / no
Could you go back from it?                    yes / no / not tried
```

Screenshots of anything that looks wrong are welcome (please do not attach files with
personal data).
