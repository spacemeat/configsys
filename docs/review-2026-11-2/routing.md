# Review: Routing + resolution engine

Baseline: `956208e` · 2026-11-08 · reviewer: opus, effort xhigh
Scope: `configsys/{adapt,componentObj,detection,errors,planning,predicate,resolve,routecheck,routes,stranded}.py`.
Context: `routes.hu` (structure: `os:` / `drivers:` / `facets:`), `docs/routing-model.md`, `docs/stranded-installs.md`,
`docs/principles.md`, `test/routing_golden.json`; to judge callers: `app.py` (`load_pipeline`, `_dispatch_op`,
`where_report`, `cmd_check`), `installState.py` (`superseded_installs`, `plan_with_swaps`), `reportgen.coverage`,
`osdetect.refine`, `tui/menu.py` (picker / overlay thread), the download drivers (`appImage`, `font`, `native_pkg_file`).
Tests read: `test_predicate`, `test_golden`, `test_routecheck`, `test_multimethod`, `test_detection`, `test_stranded`,
`test_planning`, `test_pin_collision`, `test_standing`, `test_driver_requires_gate`, `test_disabled_drivers`,
`test_version_scoped`, `test_fix_routing_resolve`, `test_version_floors`, `test_name_overrides`; test names of
`test_suggests`, `test_provider_pin_precedence`, `test_optin_provider`, `test_candidate_only` (108 test files
import an owned module; the suite was green at baseline, 2314 passed).

Every **(reproduced)** item was run with `.venv/bin/python` against scratch routes under
`$RUN/scratch/routing/` or the CLI in a sandbox `--home $RUN/scratch/routing/home*` (with `--pretend` for ops).
Scripts: `$RUN/scratch/routing/t*.py`, `perf*.py`.

**Verification (adversarial, 2026-11-08):** every CRITICAL/HIGH and every security/safety finding at MED or
above, which here is routing-01..04, was re-checked independently. Each one has a `**Verified:**` line. Verifier
scripts: `$RUN/scratch/verify-routing/scripts/v*.py`; sandbox homes: `$RUN/scratch/verify-routing/home*`.
Result: 4 checked, 4 confirmed (all reproduced), 0 refuted, no severity changes.

## Carried over from docs/review-2026-09/routing-engine.md (+ README open items in this scope)

| earlier finding | status | evidence |
|---|---|---|
| [HIGH] binding-pin whose value is also a component misread as a provider-pin (B1) | **fixed** | `c1336bd`: `resolve.pin_via_names` (`resolve.py:37-44`) shared by `_satisfy_pinned` (`:867`), `app._validate_pin`, routecheck; `test/test_pin_collision.py`. A residual on the *other* side (`_matching` treats any pin value as a binding-pin) is new → **routing-06**. |
| [HIGH] `facets: detect:` from untrusted data plugins runs shell (A2) | **fixed** | `4e45a8b` + `8a8e5d5`: `routes.load._facet_ok` (`routes.py:340-348`) merges plugin/include facets only when `command_trust` says trusted; `test_facet_trust.py`. Residual: `command_trust=None` fails open → **routing-26**. |
| [MED] `detection.py` context without `disabled` (B2) | **fixed** | `c1336bd`: `Resolver.context()` (`routes.py:589-606`) is used by every listed site (only `tools/osaudit.py` still calls `cascade.context` — pure `when:` evaluation, fine); `test_disabled_via_absent_from_the_shared_detection_context`. |
| [MED] `parts:` cycle → `RecursionError` | **open** | still no visited set (`resolve.py:711-715`), no lint → **routing-03** (now crashes `inspect` *and* `check`). |
| [MED] plugin binding without `via:` bricks the load | **open** | `routes.py:24-25` still `ValueError` → folded into **routing-04**. |
| [MED] `candidates(include_unavailable=True)` wrong `when`/`default` | **open** | unchanged (`routes.py:668-674`); and its only consumer was removed in `bcb9e9e` → **routing-29**. |
| [MED] two unrelated `ResolveError` classes | **open** | `errors.py:16` still has zero importers anywhere → **routing-30**. |
| [MED] binding-level `provides:` leaks into driver fields | **open (downgraded)** | `_RESOLVER_KEYS` (`resolve.py:482`) still lacks it; 4 bindings, no reader → **routing-31**. |
| [MED] retired vocabulary is the live identifier set | **open** | `opt_in`/`optin`/`candidate_only`/`_binding_candidate_only` unchanged → **routing-20**. |
| [MED] selection policy + private API reach-through (D6) | **open (partly)** | `Resolver.context()` landed; positional threading and `_select` reach-throughs remain, and one caller now demonstrably drops policy → **routing-18**. |
| [MED] spec drift in routing-model.md | **fixed** | `acfdecc`/`d958cf9`: schema shows `standing:`, §2 says providers aren't ranked by specificity, no "discovered", `man/configsys.hu.5` exists, config-format's `prefer:` is history. |
| [MED] test gaps 1–11 | **mixed** | fixed: 1 (`test_pin_collision`), 5 (`test_disabled_via_absent…`), 6 (`test_effective_preference_chain_order`), 8 (`test_unranked_providers_remain_ambiguous`, component-standing tests), 11 (`test_resilient_drops_a_failed_names_half_resolved_units`). open: 2 (→routing-03), 3 (→routing-04), 4 (→routing-29), 7 (→routing-24), 10 (`test_bad_syntax_raises` still 2 cases), 9 partial (golden gained fedora_atomic/void/void_musl/elementary, still x86_64-only, no alpine/opensuse/kde_linux/chimera). |
| [LOW] `predicate.subset`/`_cells` recompute per call | **open (upgraded)** | now measured at ~0.9–1.2 s per Resolver build → **routing-16** (MED). |
| [LOW] `_bindable_viable` double `_select`; `queue.pop(0)` | **open (downgraded)** | warm full resolve is 0.038 s → **routing-36** (NIT). |
| [LOW] per-via knowledge in the engine | **open** | `_package` flatpak/dotfiles/glue (`resolve.py:467-478`), `DEFAULT_DRIVER_PREFERENCE` still a code constant; the stale "snap/source ahead of their drivers" comment is gone → **routing-32**. |
| [LOW] `Os.eval` vs `_holds` facet/OS classification | **open** | `predicate.py:85` vs `:369`; no lint for a facet named like a block → **routing-22**. |
| [LOW] non-dict component value = silent tombstone | **open** | `routes.py:97` → **routing-25** (reproduced). |
| [LOW] comment drift list | **open (mostly)** | `routecheck.py:1,9`, `routes.py:314,398`, `resolve.py:75,577`, `componentObj.py:3`, tests' `'prefer' in msg` all unchanged → **routing-33**. `_pf`'s "used by tests/older callers" is **accurate** (obsolete item): bare paths are passed by `test_stranded.py:55`, `test_version_floors.py`, `test_cpu_names.py:57` and `~/src/configsys-void/test/test_parity.py:134`. |
| [LOW] OS-block `driver-preference` beats the machine setting | **fixed (decided)** | `a3c2060` made it an explicit fallback chain (`resolve._effective_preference`), documented in `docs/config-format.md:122-123`, asserted by `test_effective_preference_chain_order`. |
| [NIT] duplication (`_as_list`×3, `scale_root_of`, local imports, double key check, `_provider_index`) | **open** | → **routing-35**; `_provider_index` upgraded on measurement → **routing-17**. |
| [NIT] predicate recursion depth unbounded | **open** | → folded into **routing-04** (reproduced: a plugin `when:` bricks the load). |
| [NIT] `_FACET_CACHE` never cleared | **open** | → **routing-37**. |
| [NIT] ABI candidates (`load` tuple, `candidates` dicts, dead names, `resolve()`) | **open** | → **routing-34**, **routing-30**, dead-code section; `resolve.resolve()`'s one caller is the policy-dropping `reportgen.coverage` (**routing-18**). |
| README D6 `SelectionPolicy` / Tier F rename / return types / dead public names | **open** | routing-18 / routing-20 / routing-34 / routing-30. |
| README C4 (`diagnostics()` re-resolves) | **out of scope** | app-cli area. |

## Cross-cutting themes

- **The detection tier (and auto-tighten) exist only inside `Context.load_pipeline`.** `Resolver` keeps no
  record of the soft pins it was given, so every other consumer — the CLI op path (`_dispatch_op` →
  `resolve_with_roots`), `where`, `check`, orphans, the TUI overlay thread, `plan_companion_cleanup`,
  `dotfiles_units`, glue lookups — resolves as if nothing were installed. The worst consequence is
  routing-01 (`configsys upgrade X` uninstalls an adopted install); routing-15 and routing-19 are the same shape.
- **Resilient mode's bookkeeping has silent holes.** Errors are keyed to the *first* root that reached a
  failure, pruning runs only if some unit failed in `drain`, a part that fails in `add_component` leaves
  half a bundle, and a soft pin that breaks a hard edge becomes an error. Each is a pick with the wrong
  row (or no row): routing-02, -08, -10, -11.
- **"A plugin never bricks the load" is enforced by a path set and an exception class, not by
  provenance.** Include files, user-amended components, `ValueError`, `RecursionError` all slip past
  (routing-03, -04).
- **Manager-vs-via semantics are split.** Gates, `standing:` and `requires:` follow the manager a
  `via: native` reaches; `disabled-drivers:` follows the via *label* (routing-05). Similarly a
  `component-names` drop and a `{}` removal are documented as equivalent but differ for requirements (routing-07).
- **Expensive derived data is rebuilt per Resolver / per resolve.** The `when:` grid (routing-16) and the
  provider index (routing-17) are pure functions of the loaded data, yet each costs ~0.5–1.3 s per
  startup, per TUI reload, and per single-name resolve sweep (golden: 27.8 s → 16.9 s with one cache).
- **Policy is still threaded positionally** (D6): 11–15-arg signatures, `_select` reached into from app/TUI/
  reportgen, and one caller (`reportgen.coverage`) that silently drops four policy inputs (routing-18).
- **Lints lag the data model**: `os:` blocks (using/native), bare facet atoms, `standing:` garbage,
  `parts:` cycles are all `check`-clean while broken (routing-03, -21, -22, -24).

## Findings

### routing-01 [HIGH] safety — CLI ops ignore the detection tier: `upgrade X` uninstalls an adopted install and upgrades nothing
`configsys/app.py:816` (`_dispatch_op`) resolves with `ctx.routes.resolve_with_roots(names)` — user pins
only; `detection.detect_pins` runs solely in `Context.load_pipeline` (`app.py:480-497`) and the soft pins
are never retained on the `Resolver` (`routes.py:618-645`). So when a component is installed via a
non-default method that inspect/TUI *adopt* (`adopt-installed:` is on by default; principle "detection-first
… we manage reality, not fight it"), the CLI targets the default method, and `plan_with_swaps` →
`superseded_installs` (`installState.py:338-389`) sees the adopted install as "another method" and removes it.
For `upgrade` the paired op is `apt-get install --only-upgrade` of a package that isn't installed — so the
net effect is the app is gone. `configsys remove X` instead removes the not-installed default unit and leaves
the real install. No confirmation is asked without `--picks`. The TUI is safe (it uses the pipeline's units).
**(reproduced)** `$RUN/scratch/routing/t26.py` (sandbox home, `--pretend`, only the flatpak probe stubbed to
"installed"): `detection tier (inspect/TUI) adopts: {'multi': 'flatpak'}` then
`configsys upgrade multi` → `remove flatpak\multi … flatpak uninstall --user -y org.example.Multi` /
`upgrade apt\multi … apt-get install --only-upgrade -y multi-pkg`; `t26b.py` `configsys remove multi` →
`remove apt\multi … apt-get remove -y multi-pkg` (the flatpak stays).
**Fix:** make the effective pins part of resolution state, not of one pipeline call: compute detection pins
for the named components in `_dispatch_op` (or memoize the pipeline's `detected` on `Context`) and give
`resolve_with_roots`/`resolve_names` a `soft_pins=` path (`resolve_roots` already threads pins; add `soft`).
Belt-and-braces: `superseded_installs` should never swap away an install the detection tier would adopt
unless the user pinned the target method. Test: CLI upgrade/remove of an adopted install. **Effort:** M. **Tier:** A.
**Verified:** CONFIRMED (reproduced). I reproduced it independently, stubbing only the probe methods of the
`Apt`/`Flatpak` driver classes (multi present via flatpak, absent via apt), so the real `detection.detect_pins`,
`load_pipeline`, `_dispatch_op` and `plan_with_swaps` all run. Commands and output:
- `scratch/verify-routing/scripts/v01.py <home> pipeline` (the non-pretend `inspect` pipeline) → `adopting
  installed: multi -> flatpak`, `PIPELINE units: ['apt\\flatpak', 'flatpak\\multi']`, `flatpak\multi present= True`.
- `v01.py <home> upgrade` (= `configsys --pretend --home … --os debian:12 upgrade multi`) → `remove flatpak\multi …
  [pretend] flatpak uninstall --user -y org.example.Multi`, then `upgrade apt\multi … apt-get install --only-upgrade
  -y multi-pkg`, `rc = 0`, no prompt.
- `install multi` → the same uninstall, then `apt-get install -y multi-pkg` (a method switch nobody asked for).
- `remove multi` → only `apt-get remove -y multi-pkg`; the flatpak is left installed.

I found no guard. `_dispatch_op` passes `confirm=False` for named ops, and `_SWAP_INSTALLISH` includes `upgrade`.
The TUI (`menu._confirm_and_execute`) builds its plan from `ms.states`, i.e. the adopted units, so the CLI and TUI
disagree. Kept at HIGH rather than CRITICAL: `flatpak uninstall` runs without `--delete-data`, so `~/.var/app` user
data survives and the app can be reinstalled.

### routing-02 [HIGH] correctness — a pick that shares a failing dependency with an earlier pick vanishes (no unit, no error row)
`configsys/resolve.py:795` (`drain`) records `errors.setdefault(root, …)` for the root that *queued* the
failing edge — the first one to pull the shared unit — and `_prune_failed` (`:605-630`) then drops every
unit that hard-depends on it, including the second pick's own unit, without recording an error for that
pick. The second pick has neither a unit nor an entry in `resolve_errors`, so `stranded.classify_unroutable`
never sees it and inspect/TUI show no row at all — the opposite of "one bad pick is an error row" and of
"no surprises". It happens on shipped data.
**(reproduced)** `t22.py`: `picks [a, b] -> units [] | errors {'a': 'nothing provides "nothing-provides-this"
here (required by libc)'}`. Real catalog (`t24.py`): `amzn picks [ffmpeg, navidrome] -> units [] | errors
{'ffmpeg': 'nothing provides "rpmfusion" here (required by ffmpeg)'}`; chimera `[jdk, jdk-21]` → errors only
for `jdk`; resolving every component (`t23.py`): 22 picks vanish on chimera, 3 on amzn.
**Fix:** in `_prune_failed`, for each requested root whose own keys were pruned (or whose reach includes a
`gone` key), add `errors[root] = f'needs {dep}, which can't be installed here: {that error}'` (key the
original failure by the failing unit, then fan out to every root that reaches it). Test the two-pick case.
**Effort:** S. **Tier:** B.
**Verified:** CONFIRMED (reproduced).
- Minimal routes (`scratch/verify-routing/scripts/v02.py`; `a` and `b` both `requires: shared`, and `shared`
  requires `missing-cap`): `picks ['a', 'b'] -> units [] errors {'a': …}`. With `['b', 'a']` only `b` gets an
  error. Each pick alone does get an error.
- Real catalog through the CLI, sandbox picks `[ ffmpeg navidrome ]`:
  `configsys --pretend --home $RUN/scratch/verify-routing/home02 --os amzn:2023 inspect` → `install set:
  this-machine (2 tracked) units: 0` and `1 issue(s): ✗ unroutable ffmpeg: nothing provides "rpmfusion" here
  (required by ffmpeg)`. Navidrome gets no row and no issue (picked alone it gets
  `✗ unroutable navidrome: … (required by ffmpeg)`).
- Worse, `… install --picks` prints `configsys: nothing to do — every pick of this box is installed`, which is
  false for navidrome.
- Whole-catalog sweep (`v02b.py`): 22 picks vanish on chimera, 3 on amzn (wl-screenrec, navidrome,
  home-assistant), 0 on debian 13. This matches the reviewer.

The TUI tree also drops a pick with no units (`menu._build_tree`: `if not members: continue`). Severity HIGH kept.

### routing-03 [HIGH] correctness — a `parts:` cycle crashes `inspect`, `check` and the TUI with a RecursionError
`configsys/resolve.py:711-715` (`add_component`) recurses into parts with no in-progress set; the
`RecursionError` is not a `ConfigsysError`, so neither `resolve_resilient` nor `cmd_check` catches it, and
`routecheck.validate` has no `parts-cycle` lint. Two lines in a user config (or a plugin bundle naming a
user bundle) take the tool down — including `check`, the command meant to diagnose it.
**(reproduced)** sandbox `home4` with `bundle-a: { parts: [ bundle-b ] }  bundle-b: { parts: [ bundle-a ] }`
picked: `configsys --pretend --os debian:12 inspect` and `configsys check` both end in
`RecursionError: maximum recursion depth exceeded`; `routecheck.validate` returns `[]` (`t1.py`).
**Fix:** track `_State._parts_stack`; raise `ResolveError('parts cycle: a -> b -> a')`; add a `parts-cycle`
error to `validate()` (DFS over `via: parts` bindings). **Effort:** S. **Tier:** B.
**Verified:** CONFIRMED (reproduced). Sandbox `$RUN/scratch/verify-routing/home03` defines
`bundle-a: { parts: [ bundle-b ] }  bundle-b: { parts: [ bundle-a ] }` with bundle-a picked:
- `configsys --pretend --home … --os debian:12 inspect` → exit 1, `RecursionError: maximum recursion depth exceeded
  while calling a Python object` (the traceback goes through `resolve.add_component`).
- `configsys … check` → exit 1, same traceback.
- The TUI start, run under a pty (`script -qec "… tui"`), → exit 1 with the same `RecursionError`.
  `LoadWorker._work` captures it and `join()` re-raises it, and `main()` catches only `ConfigsysError`.
- With the cycle defined but NOT picked (`home03b`), `check` → `0 error(s), 1 warning(s) across 834 components`,
  so nothing lints it, yet `where bundle-a` still crashes.
- `routecheck.validate(...)` returns no issue that mentions the bundles.

Severity HIGH kept: one pick takes down the TUI, inspect, `where` and `check` (the diagnostic tool), and nothing
lints the cycle.

### routing-04 [HIGH] correctness — a plugin can still brick `routes.load` (includes, user-amended components, `ValueError`, `RecursionError`)
`configsys/routes.py:390-411` decides "forgiving" by `os.path.normpath(src) in {plugin root paths}`, where
`src = chain[-1][2]` is the *top* layer that touched the component. Four ways out:
(a) a component (or a `drivers:` gate, `_driver_gates` uses the same set) defined in a file a plugin
`include:`s is not in the set → loud `ConfigError`; (b) a plugin binding that makes a core component
ambiguous is skipped — unless the user's own config also amends that component, in which case the load
dies and the error names the **user's** file; (c) `Binding.__init__` raises `ValueError` for a missing
`via:` (`:24-25`), which isn't caught; (d) a deeply nested `when:` overflows the recursive-descent parser
(`predicate.py:217-257`). docs: "a malformed plugin file is skipped (never bricks the rest)".
**(reproduced)** `t18.py` → `plugin include with an ambiguous component -> ConfigError …/plugx/sub.hu:
component 'broken': two via:native bindings`; `t19.py` → `with user amend -> ConfigError` blaming
`user_amend.hu`; `t1.py` → `no-via plugin: ValueError binding without \`via\`` and
`deep plugin when: RecursionError (escapes forgiving path)`.
**Fix:** carry provenance through `layers.expand` (each `Layer` records its root path/role, so an include of
a plugin is forgiving as that plugin); judge an ambiguity by the contributing bindings' `Binding.source`
and drop only the offending plugin binding(s) with a warning; raise `ConfigError` from `Binding`; cap parser
depth (e.g. 64) with a `PredicateError`. **Effort:** M. **Tier:** B.
**Verified:** CONFIRMED (reproduced). I ran this end to end with a real plugin directory
(`<home>/.config/configsys/plugins/plugx/`, declared as `source: "github:x/plugx"`), read through
`plugins.layer_files` rather than a hand-passed `plugin_files` list. Every case is
`configsys --pretend --home $RUN/scratch/verify-routing/<home> --os debian:12 inspect`:
- **(a)** The ambiguous component in a root data file (`home04a0`) is skipped with `✗ component "broken"
  (…/plugx/main.hu): …`, exit 0. The same component in `more/sub.hu`, which `main.hu` includes (`home04a`), gives
  exit 1: `configsys: …/plugx/more/sub.hu: component 'broken': two via:native bindings (#0 and #1) overlap …`. A
  bad `drivers: { snap: { when: … } }` gate behaves the same way: in a root file it is ignored with a warning
  (exit 0); in an included file it gives exit 1.
- **(b)** If the plugin adds `{ via: native when: "cpu:x86_64" }` to core navidrome, the component is skipped
  (exit 0). Add a user `navidrome: { description: … }` amend (`home04b`) and it exits 1 with
  `configsys: …/home04b/.config/configsys/configsys.hu: component 'navidrome': two via:native bindings (#0 and #5)
  overlap …`, blaming the user's own file.
- **(c)** A plugin binding with no `via:` (`home04c`) gives exit 1 and a traceback,
  `ValueError: binding without \`via\`: {'name': 'x'}`. The TUI start under a pty crashes the same way.
- **(d)** `when: "not "×2000 debian` in a plugin (`home04d`) gives exit 1 and a `RecursionError`.

`check` fails the same way (exit 1 for 04a, 04b and 04c). One nuance: an include of a file at the plugin ROOT is
forgiving, because every root `*.hu` is itself a data file unless the manifest lists `data:`. So (a) needs an
include in a sub-directory, or a manifest `data:` list. Recovery is possible: `plugin list` still works and reports
the plugin `ok`, so `plugin rm` or `plugin lock` can undo it. Until then inspect, the TUI, ops and check are all
down, contrary to docs/plugins.md:183 ("skipped with a warning — never fatal"). Severity HIGH kept.

### routing-05 [MED] correctness — `disabled-drivers:` ignores the native manager (`[brew]` on Fedora Atomic still installs everything via brew)
`configsys/resolve.py:123-131` (`_matching`) and `:177` (`not_candidate_reason`) test `b.via in disabled`,
so a `via: native` binding is disabled only by the literal `native`. Gates, never-auto `standing:` and driver
`requires:` all follow the *manager* a native binding reaches (`driver_gated`, `_select`'s `native_drv`,
`add_component`'s `drv_reqs`), so this is the one policy input that doesn't. On `fedora_atomic` (native = brew)
`disabled-drivers: [ brew ]` disables the 266 `via: brew` bindings but every `via: native` one still becomes a
`brew\…` unit; `[apt]` on Debian is a no-op.
**(reproduced)** `t10.py`: `fedora_atomic disabled-drivers:[brew] -> ['brew\\btop', 'brew\\ripgrep',
'brew\\wget', …]`; `debian disabled-drivers:[apt] -> ['apt\\btop', …]`.
**Fix:** treat `b.via == 'native' and ctx.native_driver in disabled` as disabled in `_matching`,
`not_candidate_reason`, `_gate_note`, `gated_context`'s skip, and `stranded.find`'s 'disabled' reason; say
so in config-format.md. **Effort:** S. **Tier:** B.

### routing-06 [MED] correctness — a provider-pin on a capability that is also a component breaks that component's own pick (`pins: { jdk: jdk-25 }`)
B1 unified the classifier for `_satisfy_pinned`, but `_matching` (`resolve.py:115-119`) still treats
`pins[component.name]` as a binding-pin whatever its value. `jdk` is both a component and the capability
`jdk-17`/`jdk-25`/`graalvm` provide, so the documented provider-pin `jdk: jdk-25` makes a `jdk` pick fail
with `jdk: pinned to via:'jdk-25', which is not a binding` (consumers like scala route correctly to jdk-25).
`where jdk` labels it "pinned via:jdk-25" (`app.py:1735`), and a *detected* soft provider-pin on such a cap
logs a spurious "not adopting installed jdk -> …" line although consumers did adopt it.
**(reproduced)** `t4b.py`: `{'jdk': 'jdk-25'} ['jdk', 'scala'] -> [… 'apt\\jdk-25' …] {'jdk': "jdk: pinned to
via:'jdk-25', which is not a binding"}`.
**Fix:** in `_matching`, `Resolver.candidates`, `not_candidate_reason` and `where_report`, honor
`pins[name]` as a binding-pin only when it is in `pin_via_names()`. **Effort:** S. **Tier:** B.

### routing-07 [MED] correctness — a `component-names` `{}` drop satisfies a HARD `requires:` with nothing
`configsys/resolve.py:718-722` returns `frozenset()` for a dropped unit, and `_satisfy_pinned`
(`:895-899`) stores that as the capability's resident — the requirement reads satisfied by no unit. A
`{}`-removed component instead is not viable and errors "nothing provides". routing-model §10a says the
drop is "exactly like a `{}`-removed component"; principles: "an unmet require is an error". The same hole
makes a driver whose tool a plugin OS drops read *valid* under the derived gate (its scratch resolve
succeeds), so its bindings install without their tool.
**(reproduced)** `t7.py`: `component-names drop ['apt\\tool'] {} | deps of apt\tool: set()` vs
`{} removal ({}, {'tool': 'nothing provides "libx" here (required by tool)'})`.
**Fix:** make a dropped provider non-viable for a requirement (`_is_bindable` returns False when
`_name_override(...)` drops it for the selected driver); keep the direct-pick silent no-op. Test both.
**Effort:** S. **Tier:** B.

### routing-08 [MED] correctness — a `via: parts` bundle with one unroutable part resolves partially and order-dependently
`configsys/resolve.py:711-715`: parts are added in order; the first unroutable part raises out of
`add_component`, so earlier parts' units stay in `st.units` (attributed to the bundle) and later parts are
never added. `_prune_failed` runs only `if st.failed_keys` (`:597`), so whether those orphaned units survive
depends on whether some *unrelated* pick failed in `drain`.
**(reproduced)** `t16.py`/`t16b.py` (`bundle: { parts: [ a b c ] }`, `b` fedora-only, on debian):
`[bundle] -> ['apt\\a']` + error; `[bundle, other] -> []` + errors.
**Fix:** decide the semantics (question 3) — either skip an unroutable part with a notice (the bundle is the
union of what routes here, like `profile:` expansion) or fail the bundle atomically; in resilient mode always
prune to root-reachable units. **Effort:** S. **Tier:** B.

### routing-09 [MED] correctness — method adoption ignores an installed *default* method; binding order decides, and the next swap removes the default
`configsys/detection.py:39-57,109-117`: `_installed_via` returns the first candidate via that has a version,
in binding order; `_method` pins it whenever it differs from the resolved via. When both the resolved method
and another are installed, a first-listed alternative wins — management moves off the default, and a later
TUI upgrade's `plan_with_swaps` removes the default install. Provider adoption has exactly this guard
("if the resolved provider is itself installed, keep it", `:144-146`); method adoption doesn't.
**(reproduced)** `t14.py` (`multi: [ flatpak, native ]`, both probes "installed"): `resolved: ['apt\\multi']`,
`detect_pins … {'multi': 'flatpak'}`.
**Fix:** in `_method`, probe the resolved unit first and return None when it is installed. **Effort:** S. **Tier:** B.

### routing-10 [MED] correctness — a soft (detected) binding-pin whose method's hard requirement fails becomes an error row
`configsys/resolve.py:762-776` drops a soft pin only when *selection* fails; a soft-pinned method whose
binding-level `requires:` then fails in `drain` errors like a hard pin. routing-model §10: a detected pin
that can't be honored "is dropped for that resolution and normal selection proceeds, never an error".
**(reproduced)** `t17.py` (alpine; tool = native | glibc tarball): no detection → `['apk\\tool'] {}`;
soft pin `tool: tarball` → `[] {'tool': 'nothing auto-provides "glibc" here …'} dropped: {}`.
**Fix:** mark units selected under a soft pin; on a hard-edge failure from one, re-resolve that component
without the pin (record it in `dropped`), or pre-check the pinned binding's requires with a scratch `_State`
as `gated_context` does. **Effort:** M. **Tier:** B.

### routing-11 [MED] correctness — a provider ambiguity in a driver's `requires:` gates the whole driver; its picks read `dangling` and lose the fix
`configsys/resolve.py:238-239` (`gated_context`) gates a driver on *any* `ResolveError` from its scratch
resolve, including "ambiguous providers". Every pick that only installs via that driver then fails "no binding
… the flatpak driver can't work here (ambiguous providers …)", `stranded.classify_unroutable` (`stranded.py:220-228`)
files it as `dangling — no install method on this OS any more`, and `app.py:501-502` removes the original
error (the one naming `pins: { flatpak: … }`) from `resolve_errors`. A plugin adding a second provider of
`flatpak`/`curl`/`git`/`cargo` triggers it. CLAUDE.md: a conflict "is an error the user is told to fix …
never a silent guess".
**(reproduced)** `t9.py`: `derived gates: {'flatpak': 'ambiguous providers for "flatpak": …'}` →
`classify_unroutable: {'app': ('dangling', 'no install method on this OS any more')}`.
**Fix:** gate a driver only on unsatisfiable requirements (a `ResolveError` kind — routing-28), leaving it
valid on ambiguity so per-component resolution reports the ambiguity with its fix; classify a derived-gate
reason as an error, not `dangling`. **Effort:** S. **Tier:** B.

### routing-12 [MED] correctness — `version-floors:` changes resolution at component level only; docstring and test say it never does
`configsys/routes.py:451-467` (`_apply_version_floors`) patches both `comp.req_versions` and
`b.req_versions`, documenting "resolution is unchanged". But `add_component` reads `comp.req_versions`
(`resolve.py:751`) while re-parsing the binding's raw `details['requires']` (`:744`), so a component-level
floor selects/fails providers and an identical binding-level floor is inert (and differs from an *authored*
binding-level floor, which the resolver does read). `test_resolution_is_unchanged_by_a_floor` only covers
the binding case.
**(reproduced)** `t25.py`: `floor (comp-level) : ['apt\\py311', 'apt\\tool']`, `floor (binding) : ['apt\\tool2']`.
**Fix:** read `binding.req_versions` in `add_component` (one source of truth) and correct the docstring/§11,
or apply neither; test both levels. **Effort:** S. **Tier:** B.

### routing-13 [MED] correctness — the appImage, font and native-pkg-file drivers download with curl but don't require it
`routes.hu:222,232` (`appImage: requires [libfuse2, glibc]`, `font: requires [fontconfig, unzip]`) and no
`native-pkg-file` block at all, while `drivers/appImage.py:92`, `font.py:72`, `native_pkg_file.py:126` all run
`_CURL_DOWNLOAD`; `tarball` (`:243`) does `requires: curl`. 49 native-pkg-file and 26 appImage bindings carry
no binding-level `requires: curl` either. On a box without curl (debian/ubuntu container images; Ubuntu
desktop installs have historically shipped wget, not curl) those installs fail at run time instead of pulling
curl, and the derived gate can't decline them where curl has no route. (`source` with an archive `url:` has the
same gap — it requires only `git`.)
**(verified by reading + counts)** `grep -c "via: native-pkg-file" routes.hu` = 49, with `requires:…curl` = 0.
**Fix:** add `curl` to the `appImage`/`font` requires, add `native-pkg-file: { requires: curl }`, and a
binding-level `requires: curl` on archive-url `source` bindings; regenerate the golden. **Effort:** S. **Tier:** B.

### routing-14 [MED] correctness — `void_musl` detection uses an x86_64-only marker; ARM Void-musl detects as glibc `void`
`routes.hu:201-202`: `detect: { id: void  marker: /lib/ld-musl-x86_64.so.1 }`; `osdetect.refine`
(`osdetect.py:162-172`) requires every marker to exist (AND, exact path). On aarch64/armv7 the loader is
`ld-musl-aarch64.so.1`/`ld-musl-armhf.so.1`, so those boxes route as glibc `void` and are offered glibc
AppImages/tarballs/brew — the "installs a corpse" case the musl split exists to prevent.
**(reproduced)** `osdetect.refine('void', cascade, env={}, exists=…)`: x86_64 loader → `void_musl`;
aarch64 → `void`; armhf → `void`.
**Fix:** give `detect:` an any-of form (`marker-any: [ … ]`) or a libc probe (`ldd --version` / `/lib/ld-musl-*`
glob), and list every musl loader. **Effort:** S. **Tier:** B.

### routing-15 [MED] correctness — CLI `install`/`upgrade` re-install every already-present dependency (TUI doesn't)
`configsys/planning.py:286-305` (`expand_plan`) treats every dep as missing when `states` is None, and the CLI
caller never passes states (`app.py:860`; the TUI passes `ms.states`, `tui/menu.py:771`). So `configsys install
scala` on Ubuntu plans `install apt\curl`, `apt\git`, `apt\jdk`, `script\homebrew` (re-running the official
Homebrew installer: `sudo -v && … curl … install.sh | bash`), and dotfiles/glue links — on a host where all of
them are present, with no presence probe. `apt-get install -y <dep>` also *upgrades* an outdated dep; tarball
deps are re-downloaded and swapped, `source` deps rebuilt. The `drivers: brew` comment promises a resident brew
is "detected, not reinstalled" — true only in the TUI.
**(reproduced)** `configsys --pretend --home $RUN/scratch/routing/home3 --os ubuntu:24.04 install scala` (this
host has `/home/linuxbrew/.linuxbrew`) → `install apt\curl … install apt\git … install script\homebrew …
install brew\scala`, and no `dpkg-query`/version probe line for any dep (the planner never asks).
**Fix:** in `_dispatch_op`, inspect the dependency units (`InstallState.inspect(units)` or the probe cache)
and pass `states=` to `expand_plan`; make `states` a required keyword so a caller can't silently opt into
"everything missing". (Question 2: is the current behavior intended?) **Effort:** S. **Tier:** B.

### routing-16 [MED] performance — every Resolver build re-runs the `when:` grid: ~0.9–1.2 s per startup and per TUI reload
`configsys/resolve.py:364-378` memoizes `_most_specific_binding` per *pool of Binding objects* on the cascade,
and `routecheck.check_component` (run by every `routes.load(validate=True)`) calls `predicate.overlap` →
`witness` per same-via pair; both bottom out in `predicate._cells`/`_holds` over every OS leaf × sample. A
new Resolver (each process, and every TUI invalidate — pin edit, config edit, sync) starts cold. Measured on
the real catalog (832 components, 39 blocks): first `context()` + resilient resolve **0.765 s**, of which
1345 `subset` calls cover only **171 distinct when-text pairs**; `load(validate=True)` is 0.54 s vs 0.15 s
unvalidated (443 `witness` calls, **242 distinct** pairs). Three rebuilds in one process: 0.45 s + 0.74–0.98 s
each.
**(reproduced)** `perf1.py`/`perf3.py`/`perf4.py`/`perf6.py`/`perf7.py`; prototype memo keyed by the two
`when:` texts: `base 0.765 s → memo 0.26 s` for context + first resolve.
**Fix:** memoize `subset`/`witness` per (cascade fingerprint — lineages + scale-roots — , `a.when`, `b.when`)
in a module-level dict so it survives Resolver rebuilds (attach the source text to the parsed node); next step,
precompute one truth vector per distinct `when:` over a per-cascade grid so ⊆/overlap are bitwise. Also
precompute `OsCascade.lineage` (46,880 calls in one resolve). **Effort:** M. **Tier:** C.

### routing-17 [MED] performance — `_State` rebuilds the provider index from the whole catalog on every resolve (81% of a single-name resolve)
`configsys/resolve.py:681-686,690-695`: each `_State` (every `resolve_names`, `resolve_with_roots`,
`resolve_resilient`) walks all 832 components for `providers` and the never-auto set; only `gated_context`'s
scratch states share them. Per-name resolves are common: `where`, `reportgen.coverage` (8 per name),
`stranded.classify_unroutable`, `plan_companion_cleanup` (one per cap), glue lookups, `osaudit`/`namesweep`,
the golden.
**(reproduced)** `perf9.py` (warm caches): 832 single-name resolves 1.65 s, `_provider_index` 1.08 s cum +
the opt-in set 0.27 s. `perf10.py` caching both by `id(components)`: golden snapshot **27.8 s → 16.9 s,
identical to `routing_golden.json`** (`identical to golden: True`).
**Fix:** build `(providers, optin)` once per loaded component set (on the Resolver, or the cascade's
`__dict__` keyed like the other caches) and pass it as `shared`; reuse it in `detection.detect_pins`'
`prov_index` (`detection.py:124-127`). **Effort:** S. **Tier:** C.

### routing-18 [MED] refactor — selection policy is still threaded positionally (D6); one caller already drops it, so `request`/`report` coverage is wrong
`resolve.gated_context` (11 params), `resolve`/`resolve_roots`/`resolve_resilient` (12–15), `_State` (11),
`_select` (6) all take `pins, overrides, preference, candidate_only, disabled` positionally with `None`
defaults. `reportgen.coverage` (`reportgen.py:402`) calls `resolve([name], cascade, components, drivers,
block, version, cpu, pins)` and so resolves every platform **without** `component-names`, the machine
preference, the never-auto driver set (snap!) and disabled drivers. Eight more sites re-thread
`r.pins, r.preference, r.candidate_only` into the private `_select` (`app.py:1740`, `tui/menu.py:975,998,1880`,
`reportgen.py:176,381`, `versionreport.py:156`, `app.py:601`).
**(reproduced)** `t21.py`: 9 component × platform cells where coverage disagrees with real resolution, e.g.
`bitwarden ubuntu — coverage: ['snap\\bitwarden'], real: ['flatpak\\bitwarden']`; `helm ubuntu/debian/fedora —
coverage snap, real brew`.
**Fix:** a frozen `SelectionPolicy(pins, preference, never_auto_vias, disabled, overrides)` owned by the
Resolver; public `Resolver.select(name, *, block=None, version=None) -> Selection(binding, candidates, rule)`
and `Resolver.resolve(names, *, block=None, version=None, soft_pins=None) -> ResolveResult`; make the free
functions take the policy object (keyword-only). This deletes every `_select` reach-through and the class of
"forgot one argument" bugs. **Effort:** M. **Tier:** D.

### routing-19 [MED] refactor — the Resolver stores per-call results as shared mutable state
`routes.py:631-644` overwrites `tighten_pins`, `dropped_soft_pins` and `provider_rules` on **every**
`resolve_resilient` (15 call sites), and `context()` derives driver gates from `tighten_pins` — so the gates
`where`/the picker/detection see depend on which resolve ran last (`stranded._routes`, `plan_companion_cleanup`,
`check`, the TUI overlay **daemon thread** `tui/menu.py:2958`, `dotfiles_units` all reset them; the behavior is
pinned by `test_context_gates_under_the_last_resolves_auto_tighten_pins`). `stranded._routes_without_disabled`
(`stranded.py:240-249`) mutates `r.disabled` in place on the shared Resolver. And `where_report`'s documented
`providers <cap> by standing: N` line (`app.py:1727-1733`, CLAUDE.md, routing-model §9) reads
`r.provider_rules`, which the CLI never populates (`cmd_where` runs no resilient resolve).
**(reproduced)** sandbox `home` with ranked providers (`prov-a: standing: 2`): `configsys --os debian:12 where
consumer` prints `requires zcap` and `apt\prov-a … (dep)` but **no** `providers zcap by standing: 2` line.
**Fix:** return a `ResolveResult` (units, errors, dropped_soft_pins, provider_rules, effective pins) from every
resolve; keep the pipeline's effective pins on `Context` and pass them explicitly to `context()`; `where`
computes its own rules from a `resolve_resilient([name])` result; `_routes_without_disabled` uses
`r.context(disabled=())`-style parameters instead of mutating. **Effort:** M. **Tier:** D.

### routing-20 [MED] naming — retired vocabulary is still the live identifier set (carried)
`Component.opt_in` (`routes.py:141`), `_State.optin` (`resolve.py:685`), `candidate_only` (params of
`gated_context`, `_select`, `select_binding`, `resolve*`, `_State`; `OsCascade.candidate_only`,
`Resolver.candidate_only` read by app/menu/reportgen/versionreport), `_binding_candidate_only` (`resolve.py:339`,
imported by `routecheck.py:68`), test files `test_optin_provider.py`/`test_candidate_only.py`; `_standing`
still accepts the undocumented aliases `'candidate'`/`'never'` (`resolve.py:324`, used nowhere in routes.hu,
config.hu, examples or plugins).
**(verified by reading + grep)**. **Fix:** rename to `never_auto` / `never_auto_vias` / `_binding_never_auto`
in one pass with routing-18's policy object; drop the aliases. **Effort:** S. **Tier:** F.

### routing-21 [LOW] correctness — `os:` blocks aren't linted: a `using:` typo, a `using` cycle or an unknown `native:` pass `check`
`OsCascade.lineage` (`routes.py:216-224`) silently stops at an unknown parent or a revisit;
`routecheck.validate` checks `when:` names, `releases:` and driver gates but never a block's `using:`/`native:`.
A plugin OS with `using: debain` gets a one-block lineage (no `linux`, no `python3`, no native) and nothing
routes, with `check` clean.
**(reproduced)** `t13.py`: `lineage mydistro ['mydistro']`, `loopa ['loopa', 'loopb']`, `issues []`,
`btop: no binding for btop in this context`.
**Fix:** add `os-block` warnings: unknown `using:` parent, `using` cycle, `native:` not a registered/pending
driver, unknown block field. **Effort:** S. **Tier:** B.

### routing-22 [LOW] correctness — bare facet atoms never match and slip past `unknown-os`; facet/OS-name collisions unflagged (carried)
`routecheck.py:309-313` exempts any atom whose name is in `cascade.facet_specs`, but bare facet atoms don't
exist (`Os.eval` → False, `_holds` → False), so `when: "gpu"` (meant `gpu:nvidia`) or `when: "cuda"` silently
never matches. Separately (carried): `Os.eval` (`predicate.py:85`) treats a versioned atom as a facet when the
name isn't in *this lineage*, `_holds` (`:369`) when it isn't *any block* — a facet named like a block is read
differently by evaluation and the ambiguity checker, and nothing lints the collision.
**(reproduced)** `t20.py`: `validate` → only `('unknown-os', 'z', "…'debain'")` for `gpu`/`cuda`/`debain`.
**Fix:** warn `bare-facet` for a bare atom naming a facet; error on a facet named like an OS block.
**Effort:** S. **Tier:** B.

### routing-23 [LOW] correctness — after a non-unique most-specific, a broader binding can beat two strictly narrower ones
`configsys/resolve.py:446-449` hands the *whole* pool to `_by_preference` when no single binding is ⊆ all
others. With `native` (bare), `flatpak when: ubuntu`, `tarball when: cpu:x86_64` on Ubuntu x86, both narrow
bindings are strictly inside `native`, yet `native` wins by driver-preference — and removing the tarball
flips the default to flatpak: adding an offered method changes the default between two others.
principles.md: "A more-specific `when:` beats a broader one before any preference is consulted"; routing-model
§8a step 2 documents the whole-pool behavior. Latent: a scan of every block × {x86_64, aarch64} × component
found **0** shipped cases (`t5.py`).
**(reproduced)** `t6.py`: `winner native None by driver-preference | pool [('native', None), ('flatpak',
'ubuntu'), ('tarball', 'cpu:x86_64')]`.
**Fix:** run preference over the pool's minimal elements (bindings not strictly dominated by another pool
member); golden unchanged per the scan. (Question 4.) **Effort:** S. **Tier:** E.

### routing-24 [LOW] test-gap — `standing:` garbage is silently ignored (carried gap 7)
`_standing` (`resolve.py:312-329`) maps an unparseable value to None; `validate` has no `bad-standing` lint.
**(reproduced)** `t11.py`: `standing: high` (component), `standing: hi` (binding), `standing: "5x"` →
`validate` issues `[]`, `standing_rank 0`, `opt_in False`.
**Fix:** `bad-standing` warning (component, binding, `drivers:` block); test. **Effort:** S. **Tier:** B.

### routing-25 [LOW] correctness — a non-map component value is a silent tombstone (carried)
`routes.py:97`: `spec = val if isinstance(val, dict) else {}` turns `foo: bar` (or a typo'd one-liner) into
`{}`, which clears every lower layer's definition of `foo` with no warning.
**(reproduced)** `t1.py`: `foo: bar -> [] []` (no bindings, no issue).
**Fix:** `ConfigError('component foo: expected a map')` unless the value is `{}`/null. **Effort:** S. **Tier:** B.

### routing-26 [LOW] security — `routes.load(command_trust=None)` fails open: plugin facet probes run untrusted
`routes.py:347`: `return command_trust is None or command_trust(lyr.path)`. The app passes a trust function
(`app.py:327`), but the API default trusts every plugin/include layer's `facets: detect:` shell, and
`tools/namesweep.py:64` builds `Resolver(..., plugin_files=…)` without one. Who: a plugin's author; when: every
Resolver build in that tool; privileges: the developer's. The developer already chose to sweep that plugin, so
the delta is small — but the default should fail closed.
**(verified by reading)** **Fix:** `None` → untrusted (plugin facets dropped with the existing warning); tools
pass `command_trust=lambda p: True` explicitly. **Effort:** S. **Tier:** A.

### routing-27 [LOW] performance — `stranded.find` probes explicitly driver-gated bindings (54 `pacman -Q` spawns per catalog off Arch)
`stranded.py:150-161` probes every non-candidate binding outside `_SKIP_VIAS`. Since aur bindings dropped
`when: "arch"` (validity is the explicit `aur` gate), every aur binding is probed with `pacman -Q` on every
non-Arch machine, per startup (`stranded.augment`) and per CLI op (`superseded_installs`). An explicitly gated
driver (aur off Arch, brew on musl) can't have installed anything there.
**(reproduced)** `t15.py`: debian 13 → 72 non-candidate probes, 54 of them `aur`; pop 71/54; fedora 81/54. The
pretend install above echoes `[pretend] pacman -Q obsidian-bin` on Pop.
**Fix:** skip bindings whose driver is in the context's *explicit* gates (keep derived-gated and `when:`-gated
ones — a pre-gate AppImage is a real stranded case). **Effort:** S. **Tier:** C.

### routing-28 [LOW] data-driven — `ResolveError` carries no kind, so consumers classify by message text or re-derive
`resolve.ResolveError` is a bare message. `cmd_check` keeps only errors containing `'pinned to'` or
`'ambiguous providers'` (`app.py:2605-2609`), so a resolve-time method tie on an active pick (CLAUDE.md:
"an error row plus a check / ! issue") is not a check ERROR, while an unrelated derived-gate message that happens
to embed "ambiguous providers" is; `stranded.classify_unroutable` re-runs `candidate_bindings` and up to two
extra resolves per failing pick to rediscover what the raise site knew (and gets routing-11 wrong).
**(verified by reading)** **Fix:** `ResolveError(msg, kind=…)` with kinds unknown / no-candidate / gated /
unmet-require / ambiguous-providers / method-tie / pin-unrealizable, set at each raise; consumers switch on it.
**Effort:** M. **Tier:** D.

### routing-29 [LOW] dead-code — `Resolver.candidates(include_unavailable=True)` has no production caller, and is still wrong (carried)
`routes.py:668-674`: the "first binding per via" branch reports the wrong `when` and no default for a via
with several bindings. Its consumer (the Profiles screen) was removed in `bcb9e9e`; grep of `configsys/`,
`tools/`, `examples/`, `~/src/configsys-*` finds only `test_multimethod.py:105`.
**(reproduced)** `t2.py`: `candidates()` → native `when:'debian' default:True`; `include_unavailable` → native
`when: None, default: False`, no row marked default.
**Fix:** delete the parameter and its test (or reuse `via_representatives` if a consumer returns).
**Effort:** S. **Tier:** F.

### routing-30 [LOW] dead-code — `errors.ResolveError` (zero importers) shadows the real one; `predicate.Cpu` has no callers (carried)
`errors.py:16-26` defines `ResolveError(ConfigError)` with a `(name, os_block, detail)` constructor that no code
raises or imports; the live class is `resolve.ResolveError(ConfigsysError)` (`resolve.py:9`), which `except
ConfigError` doesn't catch. `predicate.Cpu` (`predicate.py:108-110`): no callers anywhere.
**(verified by grep)** across `configsys/`, `test/`, `tools/`, `examples/`, `~/src/configsys-*`.
**Fix:** delete both; consider basing `resolve.ResolveError` on `ConfigError`. **Effort:** S. **Tier:** F.

### routing-31 [LOW] abi — binding-level `provides:` reaches `rc.fields`; the documented `ResolvedComponent` omits `.via`/`.source` (carried, downgraded)
`_RESOLVER_KEYS` (`resolve.py:482`) lacks `provides`, so 4 bindings (`rust`, `go`, `haskell`, `cabal`) hand it to
drivers; no driver reads it (grep), but `rc.fields` is plugin ABI and the golden freezes the leak. Separately
docs/plugins.md §7 lists `.key .driver .comp .name .fields .requested_as .deps` while core drivers read
`rc.source` (dotfiles/glue content roots) and the op loop `rc.via`; plugin tests import
`configsys.componentObj.ResolvedComponent` directly (not re-exported by `configsys.plugins`).
**Fix:** add `provides` to `_RESOLVER_KEYS` (regen golden) with a generic "no resolver key reaches fields" test;
document `.via`/`.source`; export `ResolvedComponent` from `configsys.plugins`. **Effort:** S. **Tier:** F.

### routing-32 [LOW] data-driven — per-via facts live in the resolver (carried)
`_package` (`resolve.py:467-478`: flatpak's identifier is `app:`, dotfiles/glue have none),
`DEFAULT_DRIVER_PREFERENCE` (`:107-108`) as a code constant beside data overrides, `routes._VIA_ATTR`,
`stranded._SKIP_VIAS`, and the `{'native','parts'}` special set written three times (`routecheck._SPECIAL_VIA`,
`pin_via_names`, `cmd_check`'s `valid_via` at `app.py:2517`). A code plugin's driver can't declare its
identifier key. **Fix:** a `Driver.package_field` (or `drivers:` datum) and one `SPECIAL_VIAS` constant; move
the default order into routes.hu's `drivers:`. **Effort:** M. **Tier:** D.

### routing-33 [LOW] comment-drift — stale docstrings and comments (carried + new)
`routecheck.py:1` "check.py", `:3-9` "a capability's providers" are checked and "Run check_all() when loading"
(load calls `check_component`; providers aren't checked); `routes.py:5`, `:549-550` and `resolve.py:535` "a
profile's component names" (picks are the install set); `routes.py:314` docstring says a 3-tuple (returns 4);
`routes.py:398-399` "from a DISCOVERED or PLUGIN file … the profile that referenced it"; `resolve.py:75` "the old
resolver's (driver, comp, name)"; `resolve.py:577` and `app.py:470` "auto-activated project profile";
`resolve.py:424` "snap is gated `when: ubuntu`" (21 of 23 snap bindings carry no `when:` now); `routes.py:656-660`
`include_unavailable` "for the Profiles screen"; `predicate.py:3-16` grammar/semantics omit categorical facets
and version facets; `componentObj.py:3` "A profile names OS-level components"; `planning.py:3-6` says
install/upgrade (set-version too); `test_multimethod.py:4,84` and `test_routecheck.py` assert `'prefer' in msg`,
which passes only via "driver-**prefer**ence"; `test_name_overrides.py:30` uses the retired `configs:` key.
**Fix:** edit in place. **Effort:** S. **Tier:** E.

### routing-34 [LOW] abi — positional return shapes on the routing API (carried)
`routes.load` returns a positional 4-tuple that every caller unpacks (`_c, _m, _co` in tests);
`Resolver.candidates` returns ad-hoc dicts consumed by app/TUI; `Resolver.resolve_resilient` returns
`(units, errors)` with the rest left on `self` (routing-19). **Fix:** `Loaded` named tuple; a `Candidate`
dataclass; `ResolveResult`. **Effort:** S. **Tier:** F.

### routing-35 [NIT] reuse — small duplications (carried)
`_as_list` ×3 (`routes.py:169`, `resolve.py:31`, `routecheck.py:131`); `predicate.Context.scale_root_of` (`:171`)
duplicates `_scale_root` (`:331`); `routes.py:139,421` import `NEVER_AUTO, _standing` inside functions though
`:13` already imports from `.resolve`; `_check_component_keys` runs in both `_merge_component_chain` (`:98`) and
`Component.__init__` (`:124`); `detection.py:124-127` rebuilds a provider index. **Fix:** one helper each.
**Effort:** S. **Tier:** D.

### routing-36 [NIT] performance — `queue.pop(0)` and the double `_select` per provider (carried, downgraded)
`resolve.py:784` pops a list head; `_bindable_viable` selects each provider and `add_component` selects again.
Measured negligible now (a warm full-catalog resilient resolve is 0.038 s); worth folding into routing-17's
per-`_State` memo (`_select` is a pure function of the component within one `_State`). **Effort:** S. **Tier:** C.

### routing-37 [NIT] robustness — id()-keyed caches and an unclearable facet cache (carried)
`gated_context`'s key uses `id(components)`, `id(drivers)`, `id(overrides)` (`resolve.py:214-216`) without
holding references, so a caller passing transient dicts could hit a stale entry after id reuse (no production
caller does today); `_FACET_CACHE` (`routes.py:470`) is process-global with no clear hook for tests /
`configsys refresh`. **Fix:** key on the Resolver (or hold the objects in the cache); add `clear_facet_cache()`.
**Effort:** S. **Tier:** D.

## Test gaps

New tests worth adding (each pins one finding above):
1. Two picks sharing a dependency whose hard require fails → both picks have error rows (routing-02).
2. `parts:` cycle → clean `ResolveError` + `parts-cycle` lint; `check` doesn't crash (routing-03).
3. Plugin robustness matrix: an `include:`d file with an ambiguous component / bad driver gate, a plugin binding
   that makes a user-amended component ambiguous, a via-less binding, a 1000-deep `when:` — all skipped with a
   warning, blamed on the plugin (routing-04).
4. `disabled-drivers: [brew]` on fedora_atomic / `[apt]` on debian removes native bindings (routing-05).
5. Provider-pin on `jdk` with `jdk` picked (routing-06).
6. `component-names` drop of a *required* component errors like a removal (routing-07).
7. Bundle with one unroutable part, alone and alongside an unrelated failing pick (routing-08).
8. Method adoption when the default method is also installed (routing-09).
9. Soft binding-pin whose binding-level `requires:` fails falls back, recorded in `dropped_soft_pins` (routing-10).
10. Ambiguous providers of a driver's tool → an error naming the pin, not `dangling` (routing-11).
11. `version-floors:` at component *and* binding level, same resolution contract (routing-12).
12. Every download driver requires curl (a test over `drivers:` × drivers using `_CURL_DOWNLOAD`) (routing-13).
13. `osdetect.refine` for void-musl on aarch64/armhf (routing-14).
14. CLI `_dispatch_op` with present deps and with an adopted install (routing-01, routing-15).
15. CLI `where` prints the `providers` line (routing-19).
16. Golden: add `aarch64` contexts plus `alpine`, `opensuse_leap`, `opensuse_tumbleweed`, `kde_linux`, `chimera`,
    `amzn` (carried gap 9 — cpu-keyed assets, env `provides:` and the derived gates are unfrozen there).
17. `predicate` bad syntax: trailing tokens, unclosed `cpu: [`, `debian < x`, `pop_os!!`, `foo-bar`, `not cpu:`
    (carried gap 10; all behave correctly today — `t11.py` — but only two are pinned).

## Dead code

- `errors.ResolveError` — grep `ResolveError` imports across `configsys/`, `test/`, `tools/`, `examples/`,
  `~/src/configsys-*/`: every importer uses `resolve.ResolveError`. Not in driver.py's frozen list.
- `predicate.Cpu` — grep `Cpu(` / `import.*Cpu`: no callers in any of those trees.
- `predicate.most_specific`, `routecheck.check_all` — callers only in `test/test_predicate.py:60` and
  `test/test_routecheck.py:64`; not in any plugin, example or tool.
- `Resolver.candidates(include_unavailable=…)` — only `test/test_multimethod.py:105` (routing-29).
- `_standing`'s `'candidate'`/`'never'` aliases — grep of `routes.hu`, `config.hu`, `examples/`, `~/src/configsys-*/*.hu`:
  unused, and undocumented.
- **Not dead:** `routes._pf`'s bare-path form (used by `test_stranded.py`, `test_version_floors.py`,
  `test_cpu_names.py`, `~/src/configsys-void/test/test_parity.py`); `resolve.select_binding`, `resolve.resolve`
  (`reportgen.coverage`, but see routing-18).

## ABI / interface candidates

- `SelectionPolicy` + `Resolver.select()` / `Resolver.resolve(...) -> ResolveResult` (routing-18, -19), retiring the
  positional free-function entry points and every `_select` reach-through.
- `ResolveError.kind` (routing-28).
- Rename `candidate_only`/`opt_in`/`optin`/`_binding_candidate_only` → `never_auto*` (routing-20).
- `routes.load` → `Loaded`; `Resolver.candidates` → `Candidate` dataclass (routing-34).
- `ResolvedComponent`: document `.via`/`.source`, export it from `configsys.plugins`, stop leaking `provides`
  into `.fields` (routing-31).
- `planning.expand_plan(..., *, states)` required (routing-15); `routes.load(command_trust=…)` required / fail-closed
  (routing-26).
- `detect:` any-of markers for OS blocks (routing-14).

## Questions for the user

1. routing-01: should `configsys install/upgrade/remove <name>` honor `adopt-installed:` exactly like the TUI (run
   detection for the named components), and should a method swap *away* from an adopted install ever happen
   without an explicit pin or a confirmation?
2. routing-15: the `--no-deps` comment implies the default CLI path knowingly re-installs dependencies. Intended,
   or should the CLI probe deps and skip present ones as the TUI does?
3. routing-08: a bundle whose part has no route here — skip the part (with a notice) or fail the whole bundle?
4. routing-23: specificity over *minimal elements* (principles.md) or the whole pool (routing-model §8a step 2)?
   No shipped component distinguishes them today.
5. routing-07: should a `component-names` `{}` drop fail a hard requirement (as a `{}`-removed component does)?
6. routing-12: should `version-floors:` affect resolution at both levels, or neither (advisory only)?
7. routing-05: should `disabled-drivers: [<manager>]` also disable the `via: native` bindings that reach it?

## Refuted on verification

None. The four findings in verification scope (routing-01..04) were all confirmed by reproduction. Findings
below that bar (MED and lower, other than security/safety at MED or above) were not re-checked; the only
security finding, routing-26, is LOW.
