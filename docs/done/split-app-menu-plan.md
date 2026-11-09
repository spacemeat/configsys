# Split app.py and menu.py (review-2026-11-2 D2)

> **Status: DONE** — finished 2026-11-09 (commits 26e5dd8 CLI split + 0e2d083 TUI split, review-2026-11-2 D2).
> Lives on in: the module docstrings of `configsys/app.py`, `configsys/cli/*`, `configsys/tui/menu.py` and its siblings; docs/tui-architecture.md.

`configsys/app.py` (5,260 lines: the Context, every CLI command, the parser) and
`configsys/tui/menu.py` (5,230 lines: the models, the modals, the paint primitives, the samples, the
run loop) were each the place everything landed. §7 decided: full splits of both.

## Shape

**CLI** — `configsys/app.py` keeps what is the app itself: the `Context` (the load pipeline every
command and the TUI share), `main()` and its dispatch. Everything else moves, verbatim, into
`configsys/cli/`:

| module | what |
|---|---|
| `cli/parser.py` | `build_parser`, the epilog, `--version` |
| `cli/ops.py` | inspect / install / remove / upgrade / lock / unlock / set-version / fix-scope / uninstall, the plan confirm, failure reporting, System Updates |
| `cli/refresh.py` | `refresh`, the native index refresh, index-failure diagnosis + rekey, `maybe_refresh_before_plan` |
| `cli/where.py` | `where`, `search`, `location`, `versions` and their reports |
| `cli/matrix.py` | `picks`, `machine`, `profile`, `disp`, `orphans`, `pin` |
| `cli/check.py` | `check` and `check_report` |
| `cli/plugin.py` | `plugin …` (incl. init, set-source, diff, push UI, log/undo) |
| `cli/issues.py` | `report`, `request`, `request-os`, filing |
| `cli/settings.py` | `config`, `theme`, `keys`, `show`, `manpages` |
| `cli/dotfiles.py` | `dotfiles …`, `glue …` |

**TUI** — `configsys/tui/menu.py` keeps the router (`run`) and its loop helpers; the rest moves into
`configsys/tui/`:

| module | what |
|---|---|
| `tui/paint.py` | the paint primitives (`_put`, `_fit`, `_panel`, scrollbars, `_fill_bg`, wrapping, the screen chips) + `_keymap()` |
| `tui/modals.py` | every modal + overlay (`_modal_frame`, `ListNav`, popups, input box, reorder, attr filter, machines, find/filter, `?` / `!` / where, issue review) |
| `tui/help.py` | the `?` pages (`_HELP`) |
| `tui/models.py` | the Components model (`MenuState`, `Node`, the row/identity/infoblock helpers, mode switches) |
| `tui/panes.py` | the other screens' models (`ProfileScreen`, `PluginScreen`, `GlueScreen`, `DotfilesScreen`, `ConfigScreen`) + cell helpers |
| `tui/preview.py` | the Theme editor model (`ThemeScreen`) + the hand-built sample states its previews and the render tests paint (they reference each other) |
| `tui/flows.py` | execute / pin / provider pick / push flows the screens call |
| `tui/startup.py` | the inspection worker, splash choice, effects level |

## Compatibility

`configsys.app` and `configsys.tui.menu` stay importable facades: a module-level `__getattr__`
resolves a moved name from its new home, so `from configsys.app import cmd_orphans` and
`app.where_report` keep working for plugins, scripts and tests. Code inside configsys imports from
the defining module. Tests that monkeypatch a moved function patch it where it is defined (a patch on
the facade would not reach the callers).

## Validation

pyflakes clean on every new module (no undefined or unused names); the full suite; `configsys
--help`, a sandboxed `inspect`, `check`; the TUI render tests (cell-identical frames).
