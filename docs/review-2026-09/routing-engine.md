# Review: capability/component routing + resolution engine

Scope: `configsys/routes.py`, `resolve.py`, `predicate.py`, `routecheck.py`, `adapt.py`,
`componentObj.py`, `detection.py`, `errors.py`; routes.hu structure; tests
`test_routecheck.py`, `test_multimethod.py`, `test_version_scoped.py`, `test_os_blocks.py`.
All paths are under `/home/schrock/src/configsys/`. Every claim below was checked by reading
the code and, where marked **(reproduced)**, by running a script against the `.venv`.

## Cross-cutting themes

- **The engine is correct on the golden path and fast** — `routes.load(validate=True)` is 0.17 s
  and a resilient resolve of all 626 routable components (720 units) takes 0.09 s. Performance
  findings below are therefore LOW-grade micro-wins, not startup fixes; the sweep (per-OS ×
  760 components) is the only place they compound.
- **Selection *policy* is threaded positionally, not owned.** `(pins, preference, candidate_only,
  disabled)` ride through 8 resolve functions and 15+ external call sites, and 14 of those sites
  rebuild the `Context` by hand *without* `disabled`. `detection.py` is the one where that is a
  real bug. A `Resolver.context()` + `Resolver.select(name)` pair would erase the whole class.
- **The flat `pins:` namespace is decided differently in two places.** `resolve._satisfy`
  says "value is a component ⇒ provider-pin"; `app.py` says "value is a via ⇒ binding-pin".
  Eight components are *both* (`flatpak`, `pipx`, `pyenv`, `clang`, `cabal`, `opam`, `luarocks`,
  `sdkman`), so `pins: { python3.13: pyenv }` breaks any component that `requires: python3.13`.
- **Data-plugin trust boundary leaks through `facets:`.** A synced, untrusted, "definitions-only"
  data plugin may declare `facets: { x: { detect: "<shell>" } }`, and `Resolver.__init__` runs it
  with `shell=True` on every startup — the code-trust store is bypassed.
- **Retired vocabulary survives as identifiers and in docs** (`opt_in`, `candidate_only`,
  `optin`, `_binding_candidate_only`, `prefer:` in test docstrings, `opt-in:` in the spec's own
  schema block, "discovered" layers). The user is willing to break interfaces, so a rename pass
  is cheap now and costly later.
- **Two error hierarchies named `ResolveError`** (`errors.py:16` vs `resolve.py:9`) with
  different bases and constructors; the `errors.py` one has zero importers.

---

## Findings

### [HIGH] correctness — a binding-pin whose value is also a component name is misread as a provider-pin
`configsys/resolve.py:514-522` (`_satisfy`): a pin is treated as a provider-pin iff
`pin in self.components`. `configsys/app.py:1813-1824` (`_validate_pin`) uses the opposite
order: a value that is a via name is a binding-pin first. In shipped `routes.hu` eight components
share a name with a via (`cabal clang flatpak luarocks opam pipx pyenv sdkman`), and three
*required* components have a binding on such a via: `python3.13`/`python3.14` (via `pyenv`,
required by mitmproxy et al.) and `wireshark` (via `flatpak`).
**(reproduced)** with `pins: {tool: cargo}` where `cargo` is a component and `app requires: tool`:
resolving `tool` directly works, resolving `app` fails with
`"tool" pinned to 'cargo', which cannot provide it here`. Real-world trigger:
`pins: { python3.13: pyenv }` + any `requires: python3.13`.
**Fix:** one shared classifier, e.g. `pin_kind(component, value, components)` in resolve.py that
returns `'binding'` when `value in {b.via for b in components[cap].bindings}`, else `'provider'`
when `value in components`; use it in `_satisfy`, `app._validate_pin`, and
`routecheck.pin_constraint_conflicts` (`routecheck.py:160` has a third variant, `prov in valid_via`
first). Add a test with a via-named component.

### [HIGH] security — `facets: detect:` from untrusted data plugins executes shell at startup
`configsys/routes.py:233-234` merges `facets` from roles `('repo', 'plugin', 'primary')`;
`routes.py:371-374` calls `detect_facets` in `Resolver.__init__`; `routes.py:320-321` runs
`subprocess.run(str(cmd), shell=True, ...)`. `plugins.layer_files` (`plugins.py:259-280`) admits a
data plugin's `.hu` files after sync + ABI + optional checksum — **no trust approval** (trust gates
only `code:`, `plugins.py:972-1001`). So a plugin the user has *not* trusted gets arbitrary shell
on every `configsys` invocation, silently, before any install is chosen. This contradicts
docs/plugins.md's "definitions-only, plus os/drivers" description of a data layer.
**Fix (pick one):** (a) merge `facets` only from `('repo', 'primary')` and make a `plugin`-role
`facets:` a `check` warning, like `configs:`/`pins:` in includes; (b) gate plugin facets behind
the same content-hash trust as code; (c) at minimum, require `detect:` to be an argv list and drop
`shell=True`. Also worth a test: a plugin declaring a `facets:` probe must not run it untrusted.

### [MED] correctness — `detection.py` builds its context without `disabled`, so it can soft-pin a disabled via
`configsys/detection.py:74`: `cx = r.cascade.context(r.block, r.version, r.cpu)` — omits
`r.disabled`, unlike `routes.py:434`. `_installed_via` (`detection.py:45`) then lists a disabled
driver's bindings as candidates; if one is installed, `detect_pins` emits `{name: via}`
(`detection.py:115-118`), and the second resolve pass filters that via out in `_matching`
(`resolve.py:103,110`) → `no binding for X in this context (pinned to via:'flatpak')` as an error
row for a component that resolved fine before detection. The same hand-built-context pattern
appears at `reportgen.py:160,364`, `orphans.py:56`, `versionreport.py:149`, `app.py:510,1313`,
`installState.py:234,301`, `tui/menu.py:795,818,1623,2674,2938,3013` — none pass `disabled`.
**Fix:** add `Resolver.context()` (returning the disabled-aware context) and replace all 15
sites; add a test: `disabled-drivers: [flatpak]` + a flatpak-installed component must not
produce a detection pin.

### [MED] robustness — a `parts:` cycle is a `RecursionError`, not a `ResolveError`
`configsys/resolve.py:439-443`: `add_component` recurses into parts with no visited set.
**(reproduced)** `a: {parts:[b]}`, `b: {parts:[a]}` → `RecursionError`, which is not a
`ConfigsysError`, so `resolve_resilient` (`resolve.py:370-373`) does not catch it and the TUI
would crash rather than show an error row. `routecheck.validate` only checks `unknown-part`
(`routecheck.py:206-209`). A plugin can introduce this.
**Fix:** track an in-progress set in `_State` (raise `ResolveError('parts cycle: a -> b -> a')`)
and add a `parts-cycle` lint to `validate()`.

### [MED] robustness — a plugin binding without `via:` bricks the load (contradicts "never fatal")
`configsys/routes.py:24-25`: `Binding.__init__` raises `ValueError`; `routes.py:250` only catches
`ConfigsysError`, so the "forgiving" plugin path is bypassed. **(reproduced)**: a plugin file with
`broken: { install: [ { name: x } ] }` makes `routes.load` raise `ValueError` instead of
appending a `skipped component` warning. (`PredicateError` is fine — it subclasses both.)
**Fix:** raise `ConfigError` there (keep `ValueError` as a second base if any caller depends on it —
grep found none). Add a test alongside `test_plugins.py`'s malformed-file cases.

### [MED] correctness — `Resolver.candidates(include_unavailable=True)` reports the wrong `when`/`default` for a via with several bindings
`configsys/routes.py:437-443`: picks the *first* binding per via, but `winner` (`:453`) is the
most-specific binding, and `default` is `b is winner` (`:458`). **(reproduced)**: bindings
`[native, native when:debian, flatpak when:fedora]` on debian → `candidates()` says native
`when:'debian' default:True`, but `include_unavailable=True` says native `when:None
default:False` — no row is marked default. The Profiles-screen picker consumes this form.
**Fix:** for vias that are valid here, reuse `via_representatives(valid)`; only fall back to
"first binding" for vias with no valid binding. `test_multimethod.py:97-107` covers `available`
but not `default`/`when` — extend it.

### [MED] dead code / confusion — two unrelated `ResolveError` classes
`configsys/errors.py:16-26` (`ResolveError(ConfigError)`, ctor `(name, os_block, detail)`) vs
`configsys/resolve.py:9-11` (`ResolveError(ConfigsysError)`, plain message). Grep: **nothing**
imports `errors.ResolveError` (19 files import the resolve.py one). Anyone writing
`from configsys.errors import ResolveError` (the natural spelling) gets a class that no code
raises, and `except ConfigError` does *not* catch the real one because the live class skips
`ConfigError`. **Fix:** delete `errors.ResolveError`; consider re-basing `resolve.ResolveError`
on `ConfigError` (its docstring at `errors.py:12-13` already claims "unresolvable name").

### [MED] interface — binding-level `provides:` leaks into driver install fields
`configsys/resolve.py:273`: `_RESOLVER_KEYS = ('requires', 'suggests', 'parts', 'app', 'standing')`
— `provides` is missing. **(reproduced)**: `tarball\go` resolves with
`fields == {..., 'provides': {'go': '>=1.21'}}`; same for `haskell/script` and `rust/script`. Drivers
ignore unknown keys today, but `adapt.py:6-8` promises `fields` is "already the install-field
shape", and `test_multimethod.py:54-58` asserts exactly this property for `standing`.
**Fix:** add `'provides'` (and `'when'`/`'via'` defensively, though `Binding` pops them) and turn
the test into a generic "no resolver key reaches fields" check over `_RESOLVER_KEYS`.

### [MED] naming/terminology — retired vocabulary is the live identifier set
The spec (`docs/routing-model.md:300-306`, CLAUDE.md) says `prefer:`/`candidate-only:`/`opt-in:`
"are gone", yet the code's names for the concept are: `Component.opt_in` (`routes.py:128`),
`_State.optin` (`resolve.py:414`), `candidate_only` (parameter in 8 signatures, `resolve.py:212,
244,325,345,360,379,389`; attribute `Resolver.candidate_only` used at `app.py:520`,
`reportgen.py:162,366`, `versionreport.py:154`, `tui/menu.py:797,819,1624`), and
`_binding_candidate_only` (`resolve.py:150`, imported by `routecheck.py:43`). New readers must
learn two vocabularies. Since interface breaks are acceptable now: rename to `never_auto`
(component), `never_auto_vias` (the driver set), `_binding_never_auto`. Also `_standing`
(`resolve.py:135`) silently accepts undocumented aliases `'candidate'` and `'never'` — either
document or drop them.

### [MED] refactor — selection policy + private API reach-through
External modules import private engine functions: `_select` (`app.py:1293`, `tui/menu.py:790,
816,1622`), `_install_fields` (`test_multimethod.py:57`), `_prefer_rank`/
`_binding_candidate_only` (`routecheck.py:43`). Each call site re-threads
`r.pins, r.preference, r.candidate_only` positionally and hand-builds a context (see the
`disabled` bug above). **Recommendation:** a small `SelectionPolicy` (pins, preference,
never_auto_vias, disabled) held by `Resolver`, plus public `Resolver.context()`,
`Resolver.select(name) -> (binding, candidates, reason)`, and `Resolver.candidate_bindings(name)`.
`_select`'s 6-positional signature collapses to `(component, cascade, context, policy)`.
This is the single refactor with the best bug-prevention-per-line ratio in this scope.

### [MED] spec drift — `docs/routing-model.md` contradicts itself and the code
- `:69-72` schema block and `:145-148` example still use `opt-in: true`, while `:300-306` says the
  name is gone. Replace with `standing: never-auto`.
- `:345-347` and `:365-366` say provider selection picks the "most-specific provider" — the code
  (`resolve.py:543-551`) does no specificity or `standing`-rank among providers: exactly one
  ordinary viable provider or an `ambiguous providers` error. Either document "exactly one or
  pin" or implement rank/specificity (see test-gap below).
- `:417` precedence "repo < plugin < discovered < user" — the discover role was removed.
- `:52` "see configsys.hu(5)" — no such man page exists in the tree.
- `docs/config-format.md:210` still lists "a per-binding `prefer:` rank".

### [MED] test gaps worth adding
1. Pin-namespace collision (HIGH finding above) — `pins: {X: <via that is also a component>}`
   with `requires: X`.
2. `parts:` cycle → clean `ResolveError` + `check` lint.
3. Plugin binding without `via:` is skipped with a warning, not fatal.
4. `candidates(include_unavailable=True)` marks the correct default and `when` for a multi-binding
   via.
5. `disabled-drivers` × detection soft pins (needs a fake driver index; `test_disabled_drivers.py`
   only covers the pure resolver).
6. Config `preference` vs OS-block `driver-preference` *together*: `test_multimethod.py:61-71`
   tests each alone; the OS block silently wins over the machine setting
   (`resolve.py:160-164`) — pin that down or reverse it (a machine setting arguably should beat
   repo data; CLAUDE.md says "overridable per OS block", so at least assert it).
7. `standing:` garbage (`standing: high`, component-level `standing: 5`) — currently silent
   **(reproduced: `validate()` returns [])**; add a `bad-standing` lint + test.
8. Provider selection with two *ordinary* providers → the `ambiguous providers` message; and that a
   provider's integer `standing:` is ignored (document or implement).
9. Golden (`test/test_golden.py:27`) covers only `x86_64` and Debian-family/Fedora/EL/Arch; add
   `aarch64`, `alpine`, `fedora_atomic`, `opensuse_leap` contexts so cpu-keyed assets and env
   `provides:` are frozen too.
10. `predicate`: `test_bad_syntax_raises` has two cases; add trailing tokens, `cpu:` list without
    brackets, `not cpu: x` (negation over a categorical), and a facet named like an OS block
    (see LOW below).
11. `resolve_resilient`: an error in a *transitive* requires is keyed to the root
    (`resolve.py:498`) — verify a test asserts the root key, not the intermediate.

### [LOW] performance — `predicate.subset` / `_cells` recompute the grid and every lineage per call
`predicate.py:392-394`: `_cells` calls `cascade.lineage(leaf)` for all 33 blocks on *every*
`subset`/`witness` call; a full resolve made 21,801 `lineage` calls and 757 `_cells` passes
(0.09 s total, so not urgent). `check_component` (`routecheck.py:32-35`) does overlap → witness,
comparable → 2 subsets, then witness again = 4 grid passes per same-via pair;
`_method_tie_warnings` (`:57-66`) does 4 more per cross-via pair. Cheap wins, in order:
(1) precompute `OsCascade._lineage = {name: chain}` at construction (blocks are immutable after
load) and make `lineage()` a dict lookup; (2) memoize `subset(a, b)` on the cascade keyed by
`(a_when_text, b_when_text)` — `Binding.when` is the canonical text and identical strings parse
to identical match-sets; (3) in `check_component` compute `w = witness(...)` once and derive
overlap from it. These matter most for the per-OS sweep, which repeats load+check per OS.

### [LOW] performance — `_bindable_viable` runs a full `_select` per provider per requirement, then `add_component` selects again
`resolve.py:500-504` and `:434`. 912 `_select` calls for 720 units — cheap today, but the
context is fixed for a `_State`, so `_select` is a pure function of the component name there.
Memoize `_select` results per component in `_State` (a dict), which also makes
`_bindable` free. `resolve.py:490` `self.queue.pop(0)` is O(n); use `collections.deque`.

### [LOW] data-driven separation — per-via knowledge hard-coded in the engine
- `resolve.py:258-269` `_package`: "flatpak's identifier is `app`", "dotfiles/glue have no
  package" — driver facts living in the resolver. A `Driver.package_field` (or a `drivers:` datum)
  would let a code plugin's driver declare its identifier key without touching resolve.py.
- `resolve.py:94` `DEFAULT_DRIVER_PREFERENCE` is a code constant while the overrides live in
  data (`os:` blocks + config). Move the default into routes.hu's `drivers:` section
  (e.g. top-level `driver-preference:`), so plugins/OS blocks and the default are one mechanism.
  Also its comment ("snap/source are listed ahead of their drivers existing") is stale — both
  drivers ship.
- `routes.py:43` `_VIA_ATTR` and `routecheck.py:96` `_SPECIAL_VIA` are further per-via tables;
  fine as-is but candidates for the same driver-declared metadata.

### [LOW] correctness edge — `Os.eval` and `_holds` classify "facet vs OS block" differently
`predicate.py:85` (eval): a versioned atom is a facet iff the name is *not in the lineage* and a
version facet exists. `predicate.py:366` (checker): it is an OS atom iff the name is *any block*.
A facet named like an OS block that is not in this machine's lineage evaluates as a facet at
runtime but as an OS atom in the ambiguity checker. `routecheck.py:204` does not flag the
collision. **Fix:** lint `facets:` names against `cascade.blocks` (error), and make `eval` use
`name in blocks`-style classification via the context (pass `blocks` into `Context`).

### [LOW] robustness — non-dict component value is a silent tombstone
`routes.py:85-89`: `foo: bar` (a string, e.g. a typo for a one-line component) becomes `{}` and
removes/empties the component with no warning **(reproduced: `comps['foo'].bindings == []`)**.
`_check_component_keys` never sees it. Raise `ConfigError('component foo: expected a map')`
unless the value is exactly `{}`/null.

### [LOW] comment drift (fix in place)
- `routecheck.py:1` says "check.py"; `:9` "Run check_all() when loading routes.hu" — `load()`
  calls `check_component` per component (`routes.py:249`); `check_all` has only a test caller.
- `routes.py:212` docstring: `-> (OsCascade, {…}, {driver: [caps]})` but returns a **4-tuple**
  (`:269`, `candidate_only`); every caller unpacks four. Return a named tuple (`Loaded`) and fix
  the docstring.
- `routes.py:242` "from a DISCOVERED or PLUGIN file" and `resolve.py:365` "from an
  auto-activated project profile" — discovery was removed.
- `resolve.py:65` "Shaped to line up with the old resolver's (driver, comp, name)" — history.
- `componentObj.py:3` "A profile names OS-level components" — picks do; profiles are a browse lens.
- `routes.py:203-204` `_pf` "used by tests/older callers" — grep found no bare-path callers in
  the tree; drop the compatibility branch.
- `resolve.py:109` `getattr(context, 'disabled', frozenset())` — `Context` always has `.disabled`
  (`predicate.py:142`); use `context.disabled`.
- `test_multimethod.py:1-5, 54, 79` and `test_routecheck.py:258` describe `prefer:`; the
  assertions `'prefer' in msg` (`test_multimethod.py:84`, `test_routecheck.py:261`) pass only
  because "driver-**prefer**ence" contains the substring — assert `'standing'` instead.

### [LOW] design question — OS-block `driver-preference` silently beats the machine setting
`resolve.py:157-164`: any lineage block's `driver-preference:` wins over the config's global
list. On `fedora_atomic` (which sets one) a user cannot change the order except via per-component
pins. The docs agree with the code, so this is a deliberate choice — but it inverts the usual
"machine setting > repo data" rule used everywhere else (pins, `dirs:`). Worth an explicit
decision + test (gap #6).

### [NIT] duplication
- `_as_list` is defined three times (`routes.py:145`, `resolve.py:31`, `routecheck.py:99`).
- `Context.scale_root_of` (`predicate.py:168-175`) duplicates `_scale_root` (`:328-334`).
- `routes.py:127` and `:265` do `from .resolve import NEVER_AUTO, _standing` inside functions
  although `routes.py:13` already imports from `.resolve` at module level — the circular-import
  guard is unnecessary; hoist.
- `_check_component_keys` runs once per layer in `_merge_component_chain` (`routes.py:86`) and
  again in `Component.__init__` (`:112`).
- `_State._provider_index` (`resolve.py:417-422`) is rebuilt per resolve and `detection.py:122-125`
  builds a near-identical `prov_index`; cache one on the `Resolver` (components are immutable
  after load).

### [NIT] security note — predicate DSL is safe; only recursion depth is unbounded
`predicate.py` is a hand-written tokenizer/recursive-descent parser with no `eval`; the regex is
linear. A pathological `when:` (thousands of nested parens or `not`s) from a plugin raises
`RecursionError`, which is not a `ConfigsysError` and so escapes the forgiving plugin path
(`routes.py:250`). Cap nesting depth in `_Parser` (e.g. 64) and raise `PredicateError`.

### [NIT] `_FACET_CACHE` is process-global and never cleared
`routes.py:291,349`: keyed by specs+overrides JSON, so it is bounded in practice, but tests that
monkeypatch probes must remember to pass `run=` (which bypasses the cache). Expose a
`clear_facet_cache()` for tests / `configsys refresh`.

### [NIT] ABI/interface break candidates (user is OK breaking now)
- `routes.load` → return a `Loaded` named tuple instead of a positional 4-tuple.
- `Resolver.candidates` → return a small dataclass row rather than dicts.
- Drop `predicate.Cpu` (no callers), `predicate.most_specific` (test-only), `routecheck.check_all`
  (test-only), `errors.ResolveError` (no callers), `_pf` bare-path form, `resolve.resolve()`
  (one caller, `reportgen.py:387`, can use `resolve_roots(...)[0]`).
- `Binding.__init__` raising `ValueError` → `ConfigError`.
- Rename `candidate_only`/`opt_in`/`optin`/`_binding_candidate_only` (see the MED naming finding).

---

## Counts
HIGH 2 · MED 10 · LOW 7 · NIT 4
