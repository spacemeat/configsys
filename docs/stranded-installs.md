# Stranded installs and routing statuses

Routes change under machines that already have things installed. An AUR package gets promoted to
`[extra]` and its AUR binding is deleted. An AppImage is dropped, or gated to a newer glibc. A
download gains a `cpu-names:` gate. The user adds a driver to `disabled-drivers:`. The install is
still on disk, but every detection pass (inspect, the detection tier, `detect_coexisting`, the
method-switch swap) only walks a component's **current candidate** bindings, so it used to go
invisible: the component read "not installed", and installing it again doubled up
(`librewolf-bin` vs `librewolf`).

`configsys/stranded.py` closes that gap. Its result is a **routing status**, shown in place of the
install status and distinct from `outdated`:

| status | meaning | what happens |
|---|---|---|
| `switch` | installed via a method that isn't a candidate here any more (removed from routes, gated out, or its driver disabled), while another valid method exists | nothing automatic. Installing the component (TUI `i`, which "makes current" a `switch` row even when the current method is already installed, or `configsys install <comp>`) runs the method swap: the stranded install is removed first, then the current method installs (a no-op if it's already there). To choose a *different* method first, press `v` (or `configsys pin set <comp> <via>`); the method-swap offer then queues the same remove-and-reinstall. |
| `unmet` | no install method enabled, but one would be valid if a `disabled-drivers:` driver were on (for the component itself, or somewhere in its requires-closure) | not dangling. Re-enable the driver, or leave it. |
| `dangling` | no install method valid on this OS at all | never staged for removal. An existing install keeps working and shows in the row; removing it is the user's call (`configsys remove <comp>` removes the stranded install). |

Each status also gets a line on the `!` page and in `configsys inspect`.

## Finding a stranded install

Three sources, in order:

1. **Install receipts.** On every successful install/upgrade/set-version, `actions.run_plan`
   records the unit in the ledger (`state.hu`): `receipt: { via, name, fields }`. A successful
   remove clears it. This is exact, it survives the binding's removal, and it carries the fields the
   driver needs to remove the install later (an AppImage's `path`, a tarball's `installDir`, a
   flatpak's `hub`). There are no receipts for `dotfiles`/`glue`, and none under `--pretend`.
2. **Bindings still in routes but not valid here** (`when:`/cpu gated, or a disabled driver),
   probed like any candidate. `native` bindings are skipped, because a gated native binding
   describes *another* OS's package.
3. **The AUR heuristic**, for installs from before receipts existed. A foreign pacman package
   (`pacman -Qm`) named `<comp>` or `<comp>-<variant>` (`-bin`, `-git`, `-appimage`, `-nightly`,
   …), with no receipt explaining it. It's limited to packaging-variant suffixes so `go` never
   claims `go-task-bin`.

**Same package, same database, same install.** A non-candidate method that names the same package
in the same OS package database as a current method (a native manager, or a native-backed driver:
`native-pkg-file`, `aur`, the gcc/clang PPAs) is that current install, not a stranded one. Two
examples:

- gh's EL-only `.rpm` binding, gated out on Ubuntu, probes dpkg and finds the apt-installed gh.
- An AUR package promoted to `[extra]` under the same name reads as a native install, and
  `pacman -Syu` replaces the foreign build on its own.

## Plumbing

- `ComponentState.route_status` / `route_detail` / `stranded`: `status` returns the route status
  ahead of missing/locked/outdated (after unsupported/error), and `Node.status` aggregates with the
  same precedence.
- `stranded.augment` runs in `load_pipeline` after `detect_coexisting`, always, except under
  `--pretend`. It folds stranded installs into `also_present`, which is what `_offer_method_swap`
  reads after `v`. On a reload it first drops the previous verdict.
- `classify_unroutable` turns resolve errors of the dangling/unmet kind into `route_classes`
  (removed from `resolve_errors`). `unroutable_states` then adds placeholder rows: the stranded
  install's unit if one is found, else a `—\<comp>` row that `run_plan` skips with "no install
  method here".
- `installState.superseded_installs` also returns stranded installs, so `plan_with_swaps` removes
  them when the new method installs.
- `configsys remove <comp>` on an unroutable component removes its stranded install(s).
