# The `conf.yaml` editor

The **Edit .YAML** page (UI label "Editar .YAML"; key `config`, `Ctrl+5`, right
below Settings) edits `~/.config/konsave/conf.yaml`: the `save` and `export`
sections separately (group names, source folders, items, placeholders) and the
whole text, always validating with Konsave's original code before writing.

Note on interface texts: the interface is available in English and Brazilian
Portuguese. Labels and messages are quoted below as they appear in the Portuguese
interface, with an English gloss in parentheses where needed.

## 1. Audit: what the file is and how Konsave reads it

Sources: `konsave/funcs.py` (`read_konsave_config`), `konsave/parse.py`,
`konsave/conf_kde.yaml`, `konsave/conf_other.yaml`, the `conf.yaml` of
`tests/profile_test.knsv` (real Plasma 6) and probes run against the original code
(the cases are in `tests.test_config_editor.OriginalBehaviourTests`).

### Structure

```yaml
---
save:                      # goes inside the profile
    <group>:               # group name = name of the folder inside the profile
        location: "..."    # source folder, with placeholders
        entries:           # plain names of files or folders inside location
            - name
export:                    # only travels in the .knsv
    <group>: { location: ..., entries: [...] }
...
```

* Root with `save` and `export`, **both mandatory**; each is a map of groups. An
  empty `save:` (null value) breaks Konsave; `save: {}` is the right form.
* Each group has `location` (text) and `entries` (list). An empty or `null`
  `entries:` becomes an empty list when read (`read_konsave_config`).
* The real file is full of comments (including commented-out examples) and ends
  with `...`. The groups of `tests/profile_test.knsv` are `save.configs` (29
  items), `save.app_layouts`, `export.share_folder` and `export.home_folder`.
* The engine iterates over **all** root keys as if they were section groups
  (`parse_keywords`/`parse_functions`). An unknown key must therefore be a map of
  groups; otherwise Konsave fails (`TypeError`). Validation accepts valid unknown
  keys (with a warning) and refuses those that would break.

### Where `conf.yaml` is used

| Operation | Which file it reads |
|---|---|
| `save` | the **global** `conf.yaml` (`save`); copies it into the profile |
| `apply` | the **profile's** `conf.yaml` (`save`) |
| `export` | the profile's `conf.yaml` (`export`); writes a copy of the **global** one into the `.knsv` |
| `import` | the archive's `conf.yaml`; stores it in the new profile |

Editing the global file therefore applies to **future** saves and exports; profiles
already saved keep the copy they had.

### Placeholders (all checked in the original code)

They only work in `location`, never in `entries`.

| Text | Real behavior |
|---|---|
| `$HOME`, `$CONFIG_DIR`, `$SHARE_DIR`, `$BIN_DIR` | plain text substitution; the trailing slash is kept (`"$HOME/"` → `/home/u/`) |
| `${ENDS_WITH='x'}`, `${BEGINS_WITH='x'}` (single or double quotes) | replaces the **whole path** with the first folder of the parent directory whose name ends/begins with `x`. The argument cannot contain spaces (`\S+`). With two or more candidate folders, the first in the file system's listing order wins |
| `$KONSAVE_DIR` | **mentioned in `conf_other.yaml`, but does not exist** in the code: it stays literal. The editor does not offer it and refuses it |
| a function with no matching folder | Konsave **does not fail**: it returns the literal text `${FUNC='x'}` as `location` and carries on (the group is silently useless). Validation refuses it |
| a function whose parent directory does not exist | Konsave fails with `FileNotFoundError` (validation shows "O Konsave não conseguiu interpretar o arquivo", Konsave could not interpret the file) |
| two functions in the same `location` | only the last one acts; literal text is left over. Validation refuses it |
| `$NOPE`, `${FOO='x'}` | stay literal; validation refuses them first |
| `~/x`, a relative path | are not expanded; validation refuses them (must be absolute) |

The list of placeholders shown in the interface is read from Konsave's own
`parse.tokens` (`ConfigService.placeholders()`); the **interpretation** is never
redone here: the text is handed to `read_konsave_config` and the result is what the
interface shows under "O Konsave resolve esta pasta como…" (Konsave resolves this
folder as…).

## 2. How editing preserves the file

`yaml.safe_dump` would discard the comments, and `ruamel.yaml` (which preserves
them) is neither installed nor part of the dependencies. Editing is therefore
**textual and surgical** (`kongui/core/confedit.py`):

1. the text is read by PyYAML itself (the same one Konsave uses) and the exact
   positions of each group, key and item are obtained from the parser
   (`kongui/core/yamlmap.py`);
2. a form edit becomes a few line replacements, insertions and removals: renaming
   a group changes only the name, changing `location` changes only that value,
   adding an item inserts one line, removing deletes the line;
3. everything else (comments, blank lines, unknown keys, placeholders nobody
   touched, the final `...`, the user's indentation) stays **byte for byte** as it
   was; a form read and written back with no changes returns identical text
   (tested with the real `conf.yaml`);
4. the result is read again with `yaml.safe_load` and compared with what was
   intended. If anything differs, or if the layout is exotic (for example
   `save: {a: {...}}` in flow style), the text is regenerated from the data:
   **unknown keys and placeholders are kept, comments are lost**, and the
   interface warns and asks for confirmation before saving.

A null `save:`/`export:` section is corrected to `{}`. Reordering items does not
exist in the interface, and the order of groups is the file's (new ones go to the
end).

## 3. Page flow

* **Tabs**: *Seção save* (save section), *Seção export* (export section) (list of
  groups, name, source folder with placeholder buttons, items with
  add/remove/edit) and *Texto (YAML)* (text). All three show the same text;
  editing in one updates the others. If the YAML text is broken, the section tabs
  are unavailable until it is fixed.
* **Continuous validation**: on every edit the text is validated in the background
  by `ConfigService.validate_text` (the original reader). The problems panel lists
  errors and warnings with **line, column, path** (`save.configs.entries[3]`) and
  the explanation in the language in use; **Ir para** (Go to) opens the right field (or the line,
  in the text).
* **Salvar** (Save) is enabled only when the check of the current text has
  finished and has **no errors**. The service validates again and refuses if there
  is an error, even if the interface is bypassed: nothing is written and no backup
  is made.
* **Backup**: before replacing, the previous file is copied to
  `conf.yaml.bak-YYYYMMDD-HHMMSS-µs` next to it. Writing is atomic (temporary file
  + `os.replace`), keeps the permissions and, if `conf.yaml` is a symbolic link
  (dotfiles), writes to the link's target and the link stays.
* **Cancel**: *Descartar alterações* (Discard changes) goes back to what is on
  disk; leaving the page or closing the window with changes asks for confirmation.
  Nothing is written before *Salvar*.
* **Restore**: *Backups…* lists the stored versions (date, size) with a preview.
  Restoring validates the backup like any other text (an invalid backup is
  refused), asks for confirmation and **keeps the current file as a new backup**,
  so the restore can also be undone.
* **External change**: on opening, the interface stores the file's fingerprint
  (SHA-256). If another program changes it before *Salvar*, nothing is written and
  a dialog offers to reload from disk, write anyway (the one on disk becomes a
  backup) or cancel.
* **Missing file**: the page opens the default template and creates the file on
  save.
* **`--demo` mode**: edits a temporary copy of the KDE template, with real
  validation; the user's file is neither read nor written.

## 4. Errors the editor points out

Each finding has a code, path, line and column (`Problem` in
`kongui/core/results.py`), translated in `kongui/gui/messages.py`
(`PROBLEM_TEXTS`). Main ones: malformed YAML, a root that is not a map, missing
`save`/`export`, a null section, a repeated key, an invalid group name, an empty or
non-text `location`, a nonexistent placeholder or function, an unresolved or
relative `location`, `entries` missing or not a list, an item with `/` or `.`/`..`,
an unknown root key that would break Konsave. Warnings (do not block): a valid
unknown key, a repeated item, a nonexistent source folder, several functions.

## 5. Code and tests

| Piece | Where |
|---|---|
| locate line/column and end of content | `kongui/core/yamlmap.py` |
| model, surgical editing, scalar quoting | `kongui/core/confedit.py` |
| validation with positions, backups, restore, digest | `kongui/core/config.py` (`ConfigService`) |
| `ConfigSnapshot`, `ConfigCheck`, backend operations | `kongui/gui/backend.py` |
| section editor, problem list | `kongui/gui/widgets/confedit.py` |
| group, backup and choice dialogs | `kongui/gui/widgets/dialogs.py` |
| page | `kongui/gui/pages/config.py` |

```bash
python3 -m unittest tests.test_config_editor tests.test_gui_config -v
```

| Test module | Covers |
|---|---|
| `tests.test_config_editor` | core: identical read/write, edits that preserve comments and unknown keys, incomplete and exotic-layout files, special characters, 600 random edits, errors with position, backups, restore, conflict, symlink, permissions, behavior of the original engine (placeholders) |
| `tests.test_gui_config` | page: demo (memory) and real services in a temporary `$HOME`; validate, save, block errors, cancel, leave, broken text, "Ir para", backups, conflict, special characters and the real Plasma 6 `conf.yaml` |

## 6. Limitations

* The order of items and groups is not editable in the interface.
* Comments on their own lines (between groups or items) stay where they are; a
  comment written on the same line as a removed item disappears with it. If the
  edit is too exotic, the regeneration path loses the comments (and warns).
* Backups are not removed automatically (they are small files).
* The digest comparison and the write of `conf.yaml` happen under the cross-process
  lock ([`CONCURRENCY.md`](CONCURRENCY.md)); other programs that do not use the lock
  can still change the file, and that is only detected at write time.
* A group's source folder is validated, but the content of the items is not
  checked on disk (Konsave silently ignores what does not exist).
