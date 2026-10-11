# Stranded installs and routing statuses

> **Status: REFERENCE** — stranded-install detection + the `switch`/`unmet`/`dangling` routing statuses (configsys/stranded.py); maintained.

Routes change under machines that already have things installed. An AUR package gets promoted to
`[extra]` and its AUR binding is deleted. An AppImage is dropped, or gated to a newer glibc. A
download gains a `cpu-names:` gate. The user adds a driver to `disabled-drivers:`. The install is
still on disk, but every detection pass (inspect, the detection tier, `detect_coexisting`, the
method-switch swap) only walks a component's **current candidate** bindings, so it used to go
invisible: the component read "not installed", and installing it again doubled up
(`librewolf-bin` vs `librewolf`).

`configsys/stranded.py` closes that gap. The invariant (docs/principles.md): **a route change never
strands an install silently, and never acts on it silently** — nothing is staged automatically and
nothing is removed for the user. Its result is a **routing status**, shown in place of the install
status and distinct from `outdated`:

| status | meaning | what happens |
|---|---|---|
| `switch` | installed via a method that isn't a candidate here any more (removed from routes, gated out, or its driver disabled), while another valid method exists | nothing automatic. Installing the component (TUI `i`, or `configsys install <comp>`) runs the method swap: the stranded install is removed first, then the current method installs (a no-op if it's already there). `menu.OPS['install']` deliberately allows `i` on a `switch` row even when the current method is already present ("make current"). To choose a *different* method first, press `v` (or `configsys pin set <comp> <via>`); the method-swap offer (`_offer_method_swap`) then stages the same remove-and-reinstall. |
| `unmet` | no install method enabled, but one would be valid if a `disabled-drivers:` driver were on — the method's own driver, a driver its driver's `requires:` need (the derived driver gate: on Arch snapd installs only via aur, so disabling aur gates snap too), or one somewhere in the component's requires-closure | not dangling. Re-enable the driver, or leave it. `i` is never offered. |
| `dangling` | no install method valid on this OS at all | never staged for removal; `i` is never offered. An existing install keeps working and shows in the row; removing it is the user's call (TUI `x` on the row, or `configsys remove <comp>` — both remove the stranded install). |

Each status also gets a `warn` line on the `!` page and in `configsys inspect`
(`stranded.diagnostics`). A stranded install also appears in the row's "also present" list, labelled
`stranded` with its reason, instead of the usual "pin it to manage" hint: routes don't offer that
method here, so it can't be adopted with a pin — only swapped out.

A tracked component with a routing status stays in the TUI Components screen's default **to-do**
view (`menu._TODO_STATUSES` = `missing`, `outdated`, `switch`, `unmet`, `dangling`), so a stranded
install surfaces without switching views. (Routing statuses rank ahead of missing/outdated in
`ComponentState.status`, so they have to be listed explicitly.)

## Finding a stranded install

`stranded.find(ctx, comp)` checks three sources, in order:

1. **Install receipts.** After every successful install/upgrade/set-version (including an
   install that succeeded with a warning or wasn't detected afterwards), `actions.run_plan` records
   the unit in the ledger (`state.hu`, keyed by unit key) via `Ledger.set_receipt`:
   `receipt: { via, name, fields }`. A successful remove clears it (`clear_receipt`). This is exact,
   it survives the binding's removal, and it carries the fields the driver needs to remove the
   install later (an AppImage's `path`, a tarball's `installDir`, a flatpak's `hub`). There are no
   receipts for `dotfiles`/`glue` (config drivers, not install methods) and none under `--pretend`.
   A receipt whose install is no longer on disk is ignored.
2. **Bindings still in routes but not valid here** (`when:`/cpu gated, or a disabled driver),
   probed like any candidate. `native`, `parts`, `dotfiles` and `glue` bindings are skipped: a gated
   native binding describes *another* OS's package (it would map onto this OS's manager only by
   accident), and the others aren't install methods of their own.
3. **The AUR heuristic**, for installs from before receipts existed. A foreign pacman package
   (`pacman -Qm`, via the aur driver's `foreign_index`; off Arch this source is absent) named
   `<comp>` or `<comp>-<variant>` (`stranded.AUR_VARIANTS`: `-bin`, `-git`, `-appimage`, `-nightly`,
   …), with no receipt explaining it. It's limited to packaging-variant suffixes so `go` never
   claims `go-task-bin`.

Each find carries a **reason** (`REASON_TEXT`): `removed` (no binding in routes describes that
package any more — including a binding that now names a different package, `antigravity-bin` →
`antigravity`), `gated` (a binding still describes it but isn't valid here), or `disabled` (its
driver is in `disabled-drivers:`).

**Same package, same database, same install.** A non-candidate method that names the same package
in the same OS package database as a current method (a native manager, or a native-backed driver:
`native-pkg-file`, `aur`, the gcc/clang PPAs) is that current install, not a stranded one. Two
examples:

- gh's EL-only `.rpm` binding, gated out on Ubuntu, probes dpkg and finds the apt-installed gh.
- An AUR package promoted to `[extra]` under the same name reads as a native install, and
  `pacman -Syu` replaces the foreign build on its own.

## Plumbing

- `ComponentState.route_status` / `route_detail` / `stranded`: `status` returns the route status
  ahead of missing/locked/outdated (after unsupported/untrusted/error), and `Node.status` aggregates
  with the same precedence (`dangling` > `unmet` > `switch`, `stranded.ROUTE_STATUSES`).
- `stranded.augment` runs in `Context.load_pipeline` after `detect_coexisting`, always (a safety
  check, not gated by `detect-coexisting:`), except under `--pretend`. It folds stranded installs
  into `also_present`, which is what `_offer_method_swap` reads after `v`. On a reload it first drops
  the previous verdict.
- `classify_unroutable` turns resolve errors of the dangling/unmet kind into `Context.route_classes`
  (removed from `resolve_errors`; other failures — ambiguity, unknown component — stay errors).
  With no candidate, it re-asks `candidate_bindings` under `r.context(disabled=())`: a hit is
  `unmet` (naming the disabled driver directly, or "needs a disabled driver" when the hit's driver
  is only derived-gated), no hit is `dangling`. With a candidate, it compares `resolve_resilient`
  with and without `disabled-drivers:` to catch a requires-closure broken by a disabled driver.
  `unroutable_states` then adds placeholder rows: the stranded install's unit if one is found, else
  a `—\<comp>` row that `run_plan` skips with "no install method here".
- `installState.superseded_installs` also returns stranded installs, so `plan_with_swaps` removes
  them when the new method installs (remove-before-install ordering is `expand_plan`'s), and
  `plan_companion_cleanup` drops the old method's glue companions with them.
- `configsys remove <comp>` on an unroutable component (`_dispatch_op`) removes its stranded
  install(s).
