# configsys code review — 2026-11-08

Baseline: `956208e` · reviewers: opus, effort xhigh (security max), checkers: opus, effort max
Areas: 16 (routing, config-layers, plugins, primary, drivers-os, drivers-lang, dotfiles-glue, app-cli,
actions, subsystems, tui-core, tui-screens, tui-theme, tests-tools, security, parity) · not reviewed:
none (tests-tools needed three runs — two usage-limit cut-offs).
Health at baseline: 2314 tests passed (500 s); `check` 0 errors on pop/fedora/arch/opensuse/rhel/void,
1–2 on alpine/void_musl/fedora_atomic (this machine's own pins — not tree errors), 6 warnings each (the
plugin ambiguity warnings + the python-3.10 advisory); docaudit 0 findings.
Findings (16 areas, after verification): **5 CRITICAL · 36 HIGH · 149 MED · 185 LOW · 31 NIT** —
81 checked by 16 checkers: **81 confirmed (60+ reproduced), 0 plausible, 0 refuted**, 11 severity changes ·
components: 184 broken / 163 drift / 221 opportunity / 142 note (§5).

This is the first full-tree review since 2026-09 and the first with an adversarial checker on every area.
The tree is in good shape structurally — the 2026-09 refactors landed (shared batch_index, run_plan,
NativePkgManager, the MVVM screens, the primary journal), 123 earlier findings are confirmed fixed — but
the review found a **trust-boundary gap the 2026-09 A1 fix only closed for `script`/`source`/`glue`**, two
**data-loss paths** in everyday commands (scalar config edits; deleting a plugin clone with unpushed
work), and a cluster of **"looks safe, isn't" destructive paths** (dotfiles `src:` with `..`, partial rm
guards, glue reverting through symlinks). No checker refuted anything: the reviewers' bar was high, and
the HIGH/CRITICAL counts can be trusted.

The run itself: two usage-limit cutoffs (03:58 and ~13:00) stopped agents mid-task; every interrupted area
was re-run. One component auditor ran `pipx install ansible` / `ansible-core` on the real home through an
unquoted heredoc (08:42) — reported to you, not undone (its uninstall was refused by the permission
check); a checker's non-`--pretend` sandbox run planned a real `apt-get remove btop` that a missing sudo
stopped. Both rules are now in the agent briefs.

The brief: (the user's brief, verbatim — see `.claude/skills/review-code/SKILL.md` "The brief")

## Progress (updated as work lands)
- 2026-11-08 — review written; report-only run (no fixes applied, per your choice).
- 2026-11-08 — A17 — the suite is hermetic (conftest guard); A2 A3 A4 A5 A7 B2 follow.
- 2026-11-08 — A1 trust gate, A6/A9 destructive-path guards, A8 config drivers never write through links, B1+D3 one plan builder (CLI honors adopted installs; only missing deps).
- 2026-11-08 — B3 B12 B13 — bash loads glue everywhere, fish appends, zsh no longer leaks null_glob, the launcher works through symlinks / from your CWD / on EL 9.
- 2026-11-08 — D8 — derivatives resolve like their base (Zorin/Mint/elementary/LMDE/MX).
- 2026-11-08 — C1 — batched candidates for every native manager.
- 2026-11-08 — C2 — Profiles triage keys no longer rebuild the Resolver.
- 2026-11-08 — C3 — startup re-resolution trimmed (seeded start 2.45 s -> 1.42 s; rebuild 1.7 s -> 0.7 s).
- 2026-11-08 — C4 — version caches consolidated; suite 9 min -> 4 min.
- 2026-11-08 — C5 — shell startup: cs_loc O(1), no per-start pyenv rehash.
- 2026-11-08 — C6 — TUI per-keystroke + preview costs, dnf versionlock.
- 2026-11-08 — B4 — bad data no longer bricks load.
- 2026-11-08 — B5 — no pick vanishes without an error row.

## 0. Fixed during the review
None — report-only.

## 1. The earlier review

docs/review-2026-09 (baseline `7a395c5^`) and docs/review-2026-11 (primary, all 37 closed). Across the
areas' carry-over tables: **123 fixed, 200 still open, 19 obsolete**. Of the 2026-09 ranked items:
- fixed: A2 A3 A4 A6 A8 A9, B1–B4 B7 B10, C1 C2, D2 (MVVM), F1, most of D1/D3/D4.
- **still open → now ranked here:** A1 (only partly — see A1 below), A5 (→ A5), A7 asset checksums (→ A1),
  A10 key/source paths (→ A1), B9 version-cache race (→ C4), C3–C5 (→ C3, C4), D1 remainder `_alt`/
  native-pkg-file (→ D-tier), D4 ModuleDriver (→ D5), D5 settings registry (→ D1), D6 SelectionPolicy (→ D6),
  D7 LinkedContentDriver (→ D4), D8 plugins Humon I/O (→ A2), D9 split app.py (→ D2), Tier F names (→ F).

## 2. Cross-cutting themes

1. **Trust is enforced per driver, not per layer** (security, plugins, drivers-os, drivers-lang,
   dotfiles-glue, subsystems, tui-theme, config-layers). `command_trusted` is called by 3 drivers; every
   other way a plugin layer can run, download, place, or rebind something is ungated — and the docs say
   it's refused. The fix that ends the class is ONE gate at resolution: an untrusted layer's bindings that
   carry commands, privileged writes or downloads are not candidates (with a clear "untrusted" row).
2. **Destructive operations without a "what would I destroy?" check** (actions, tui-screens, parity,
   drivers-lang, dotfiles-glue, primary, config-layers, subsystems). rmtree of clones, source checkouts,
   install dirs and dotfiles targets trusts paths and state it never inspects. One shared
   `safe_remove(path, owner_marker, refuse=[home, scope bases, shared dirs])` + a git-state check for clones.
3. **The CLI and TUI still diverge on plan semantics** (app-cli, routing, actions, tui-core, parity): the
   detection tier, locks, dependency re-installs and `x`/`L` scope differ by surface. Plan building is still
   two implementations (actions-16) — the unfinished half of 2026-09 D3.
4. **Text-surgery writers aren't validated after writing** (config-layers, plugins, primary, tui-theme):
   hutext span errors delete neighbours; humerge loops; `.hu` files settled in an editor aren't re-parsed.
   Re-parse-and-compare after every write would have caught all of them.
5. **Startup/keystroke cost lives in re-resolution** (routing, app-cli, config-layers, tui-screens, tui-core,
   subsystems): Resolver rebuilt per config edit, `when:` grid per build, provider index per resolve,
   versions.hu per unit; non-apt managers have no batched candidate index (10× on Fedora).
6. **Derivative OS lines drift from their base** (os-releases): gates that name only `ubuntu`/`debian`
   versions miss Zorin/Mint/elementary/LMDE/MX; the registry now knows each one's base and could evaluate it.

## 3. Act-on-these, ranked

### Tier A — security and safety

- **A1 [CRITICAL] Untrusted plugins can run commands as root and place binaries.** A data-only plugin (no
  trust prompt) can add a narrower binding to a picked component and get: apt `ppa:`/`source-line:`/
  `pubkey-*` and dnf `repo-*` (gpgcheck=0) run as root; `native-pkg-file` installs an arbitrary `.deb`/`.rpm`;
  `_alt` vendor repos; system-scope tarball/appImage downloads (the appImage is *executed* as root); `via:
  dotfiles` templates into `~/.zshenv`; `version: { url: }` fetched at inspect with your GitHub token;
  receipts that drop the binding's source so a removed plugin's script still runs as trusted. Docs
  (plugins.md §6) say all of this is refused until trust. Checkers split on CRITICAL vs HIGH (it needs a
  hostile plugin + an install); ranked CRITICAL because it is the exact boundary 2026-09 A1 meant to close.
  **Fix:** gate at resolution (theme 1) + `ships_executable_data` covers every such field; asset
  `sha256:`/https for downloads (A7); keyring/sources paths confined (A10). (security-01/02/04/06/07,
  plugins-01/05, drivers-os-01, drivers-lang-04/05, dotfiles-glue-21, actions-07, subsystems-04,
  config-layers-04) · effort L → plan doc · [done 48507e9 — one trust gate at resolution (trustgate.py): untrusted layers contribute only packages by name from trusted registries; run_plan re-check; receipts carry source; primary-trust setting; vendor paths confined; code:/data: contained; v2 identity; https-only version fetch; sha256: on downloads — docs/done/trust-gate-plan.md]
- **A2 [CRITICAL] Editing a scalar setting deletes the lines after it.** `hutext.value_end` treats a quoted
  value as trivia → `config set`/`machine use`/TUI Config on `machine: "laptop"` deletes the next key's
  line (your `picks:`), or truncates a one-line file. Same family: `remove_sections` deletes the wrong span
  (plugins-02), `set_section`'s insert fallback corrupts degenerate files (plugins-03), quoting misses `//`
  and `/*` so a `locations:` path can come back as `~/apps` and be `rm -rf`'d (config-layers-02).
  **Fix:** scalar_end in hutext (humerge already has it) + re-parse-and-compare before every write
  (theme 4). Your files don't have the triggering shape today. (config-layers-01/02, plugins-02/03) ·
  effort S–M · [done f1ce9e7 — hutext scalar spans end at the token; quoting covers // and /*; keys/lists quoted; depth-aware insert; remove_sections on hutext spans; every edit re-read before writing (refused, file untouched)]
- **A3 [CRITICAL] Removing or replacing a plugin destroys unpushed and uncommitted work.** `plugin remove`,
  `plugin add --replace`, and Plugins `x` (one keypress, no confirm) rmtree the clone without checking git;
  for the primary that is your journal commits and — after `plugin init` — the only copy of your captured
  dotfiles (live links dangle). `--replace` also drops `primary: true`. **Fix:** refuse with a list of what
  would be lost unless `--force`; keep a `.replaced-<date>` copy; confirm popup on `x`; carry
  `primary`/`ref` on replace. (actions-01, tui-screens-01, parity-01) · effort M · [done a80cc91 — plugin remove / Plugins x refuse a clone holding unpushed/uncommitted work, stashes, no remote or authored in place (naming it; --force); --replace keeps such a copy as <name>.replaced-<stamp> and keeps primary]
- **A4 [HIGH] A dotfiles `src:` with `..` makes capture rmtree any directory — your home included.**
  Unvalidated route paths; on a first capture no `--force` is needed; in the TUI one `m`/Enter. Also:
  capture follows symlinks (`keys -> ~/.ssh`) into the store, past the secret scan, and into the primary.
  **Fix:** reject absolute/`..` `src:`; resolve-and-contain before every rmtree; don't follow symlinks out of
  the source tree. (dotfiles-glue-05, -04) · effort S · [done 1d474b7 — dotfiles src: must be relative/no .., dst:/absorb-into: under home (routecheck error + driver skip); rmtree/relocate contained; capture copies links as links, skips links out of the config and private-key files]
- **A5 [HIGH] A plugin that `include:`s your top config demotes it** — pins, picks, machine, scope,
  disabled-drivers vanish and `primary-verify: signed` reads `off`; your overrides sink below the
  plugin's. 2026-09 A5, still open. **Fix:** the top config is never an include target (dedupe keeps the
  highest role). (security-03, config-layers-03) · effort S · [done 9e8d60b — an include of a root layer (top config, primary, repo) is ignored with a warning; a plugin include must stay inside its own checkout]
- **A6 [HIGH] Destructive-path guards are partial.** tarball `installDir: ../…` escapes the scope-base guard
  and `~/.local/bin` / `/usr/local/bin` aren't refused; install doesn't check the marker (uninstall does);
  font `locations:` → `rm -rf` anywhere; `locations:` paths unvalidated (CWD-relative; `~` is the real home
  under `--home`). **Fix:** one `safe_remove` (theme 2). (drivers-lang-02, subsystems-02, config-layers-07) ·
  effort M · [done 48507e9 — Driver.unsafe_dir_reason + replace_dir_refusal before every rm -rf / mv-over (tarball, font, source, appImage); unowned dirs need --force; binary:/exe: are names; locations: absolute or ~ (configsys home), normalized]
- **A7 [HIGH] TUI `x`/`L` on a component also removes/holds its shared dependencies** — `x` on a brew
  formula removed Homebrew + git + curl (apt then takes rust, cargo, steam); the confirm lists units only.
  The CLI touches only the component. **Fix:** act on `resolve_with_roots([name])` like the CLI. (tui-core-01)
  · effort S · [done 8f9ee56 — remove/lock/unlock act on a row's own units (bundle: its parts; profile: its components' own units); deps only from their own rows]
- **A8 [HIGH] Glue/dotfiles writes through symlinks into your portable configs.** The shell-writes guard
  reverts THROUGH the `zsh-dotfiles` link (overwriting your captured zshrc in the primary); removing
  `shell-glue` strips the loader block through it; `dotfiles` uninstall restores `.pre-configsys` over a
  live config. (dotfiles-glue-01/03/17) · effort M · [done 48507e9 — shell-writes guard skips dotfiles/glue and never writes through a link; dotfiles uninstall removes only its own link and restores into the gap only; glue removal leaves a linked rc alone]
- **A9 [HIGH] `source` install wipes a pre-existing checkout's uncommitted work; uninstall/method-swap
  then `rm -rf`s it.** (drivers-lang-01) · effort S · [done 48507e9 — source trees: .cloned/.adopted markers; an unowned checkout is refused (install --adopt builds there without cleaning); local changes need --force; remove deletes only a clean tree configsys created]
- **A10 [HIGH] A streamed sudo / warm-batch op runs twice when the child prints a non-UTF-8 byte.**
  (subsystems-01) · effort S · [open]
- **A11 [HIGH] An untrusted plugin's `keys:` can turn `j` on the Plugins screen into "trust every plugin";**
  and `t`/`T`/`b` grant trust on one unconfirmed keystroke. **Fix:** trust/bless actions not rebindable
  from plugin layers + a confirm. (tui-theme-01, parity-07) · effort S · [done 48507e9 — keys stay rebindable; a plugin's keys: count only once it is trusted (Config.key_layers; check names ignored ones) — with A1]
- **A12 [HIGH] `plugin push` combines the remote into a primary you LOCKED** (and auto-push does it on any
  CLI edit). (primary-02) · effort S · [open]
- **A13 [MED] Primary edge-case data loss:** "Stop" deletes an ignored file of yours; `plugin undo` of a
  commit that moved files in deletes the only copy; the tag→branch switch bypasses PrimaryRepo and syncs
  locked plugins; a submodule breaks `_combine`'s stash assumption; Ctrl-C still commits. (primary-03/05/
  06/07/08) · effort M · [open]
- **A14 [MED] `--pretend refresh` hits the network and writes the version cache; `refresh` offers to delete
  the vendor source of an installed-but-unpicked component** (it prompts under --pretend against the real
  /etc). (app-cli-02/03) · effort S · [open]
- **A15 [MED] Glue/dotfiles safety, the rest:** glue backs up a displaced file only once (second real file
  clobbered); a shell start can trigger a bootstrap repair incl. `sudo apt-get`; the shell-writes guard
  covers 5 bash/zsh files only; nu/elvish inline blocks go stale silently; "move to local" deletes the config
  from your primary for every machine without a confirm. (dotfiles-glue-06/12/14/20/22) · effort M · [open]
- **A16 [MED] Misc hardening:** aur builds in a fixed shared `/tmp/configsys-aur` (another local user can
  pre-create it); `--home` isn't a sandbox for module installers (commands use the ambient `$HOME`); the
  report scrubber misses URL-embedded credentials and non-GitHub tokens. (drivers-os-06, drivers-lang-06,
  subsystems-03) · effort S · [open]

- **A17 [HIGH] The test suite touches the developer's real machine:** a unit test runs real `sudo -v` and
  `sudo apt-get update`; tests read and write the real config (`--home` loses to ambient env), and a global
  git config breaks 105 tests; a fixed world-writable `/tmp/nohome` is trusted as a configsys home.
  **Fix:** an autouse conftest fixture that scrubs `CONFIGSYS_*`/`GIT_CONFIG*`/`HOME`, a fake `sudo` first on
  PATH, and a per-test tmp home. (tests-tools-01/02/03) · effort S–M · [done 53461a6 — hermetic conftest: tmp HOME, CONFIGSYS_*/XDG_* scrubbed, git config isolated, fake sudo, Runner guard + real_runner marker; no fixed /tmp/nohome]

### Tier B — correctness

- **B1 [HIGH] CLI ops ignore the detection tier:** `upgrade X` uninstalls an adopted install and upgrades
  nothing; `remove` misses it; `location` points elsewhere; CLI install/upgrade re-installs every present
  dependency (the TUI doesn't). (routing-01/09/15, app-cli-01/04) · effort M · [done 48507e9 — actions.resolve_targets: CLI ops resolve through auto-tighten + the detection tier; detection keeps an installed default method (routing-09)]
- **B2 [HIGH] Version locks kept in the ledger aren't honored** by `u`/`U`/`i`/`I` or `configsys upgrade
  <name>` (67 default methods on pop are ledger-locked). **Fix:** guard in `run_plan`. (actions-02,
  tui-core-02, parity-02) · effort S · [done 8f9ee56 — run_plan refuses an explicit upgrade of a locked unit (ledger or native hold), remove ends the lock, set-version re-holds, a lock follows a method swap; TUI U/I skip locked, u says why]
- **B3 [HIGH] Bash glue loads only where `~/.bashrc` sources `~/.bash_aliases`** — Debian-family only; on
  Fedora/RHEL/Arch/Void/Alpine no bash glue runs. (dotfiles-glue-02) · effort S · [done — bash glue is a ~/.bashrc block like zsh (created where absent, + a .bash_profile where no login profile exists); the Debian-only ~/.bash_aliases link retires; a linked bashrc is never edited]
- **B4 [HIGH] Bad data still bricks load:** a `parts:` cycle (RecursionError in inspect/check/where/TUI);
  a plugin include/ambiguity/no-`via:` binding/deep `when:`; a malformed version constraint anywhere.
  (routing-03/04, subsystems-05) · effort M · [done — parts cycle = an error row + a check parts-cycle error; via-less binding / pathological when: are load errors (forgiven for plugins); every file in a plugin checkout is forgiving; a plugin that makes your amended component ambiguous is dropped with a warning; constraint operands strip v and an unreadable one abstains (+ check bad-constraint)]
- **B5 [HIGH] A pick that shares a failing dependency with an earlier pick vanishes** — no unit, no error
  row; `install --picks` then says everything is installed. (routing-02) · effort S · [done — a pick whose unit went with a shared failed dependency gets its own error row naming the cause]
- **B6 [HIGH] A metatag inside a list makes humerge loop forever** (push hangs, memory grows). (primary-01)
  · effort S · [done — humerge refuses (Unmergeable → the normal question path) a list holding a metatag, and never loops on an item it cannot read]
- **B7 [HIGH] `_alt` (clang/gcc) vendor-repo setup can leave a poison-pill apt source** (derivative
  codenames, a PPA on Debian, no validate/rollback). (drivers-lang-03) · effort M · [open]
- **B8 [HIGH] Theme export/promote drops the Theme page and unlisted roles; promote then deletes the local
  original.** (tui-theme-03) · effort S · [open]
- **B9 [new, found by a checker] `plugin init` moves the dotfiles store but never re-points the live links**
  — every linked config dangles. (parity-01 verification note) · effort S · [open]
- **B10 [MED] The ledger isn't robust:** last-writer-wins across processes; written in place and loaded
  intolerantly (a truncated `state.hu` bricks every command); `run_plan` isn't exception-safe.
  (actions-03/04/05) · effort M · [open]
- **B11 [MED] Settings validation is uneven:** a <10-byte config fails to load (`{}` bricks configsys);
  values parsed three ways (`reboot-advice ture` = off); `check` says 0 errors with an unreadable primary
  file; typo'd picks pass. (config-layers-05/06/08, actions-11, app-cli-08) · effort S · [open]
- **B12 [MED] Bootstrap:** can't start on EL 9 / Amazon Linux 2023 (python3 3.9 — also in os-releases.md);
  `configsys.sh` `cd`s so relative CLI paths resolve against the clone; a symlinked launcher misfinds the
  repo. (dotfiles-glue-09/10/11) · effort S–M · [done — configsys.sh resolves its symlink, keeps your CWD for relative paths (CONFIGSYS_INVOKED_CWD), and picks the first python3/3.14…3.10 >= 3.10 (EL 9, AL2023) with a PYTHON= hint]
- **B13 [MED] fish `fish_add_path -ga` doesn't append** — Homebrew and 13 "append" snippets land AHEAD of
  /usr/bin (incl. today's homebrew glue); zsh loader leaks `null_glob`; a non-UTF-8 rc aborts `arm`;
  "hooked up" reported when nothing was. (dotfiles-glue-07/08/13/18) · effort S · [done — fish appends with -gaP; zsh uses *.zsh(N) (no leaked null_glob); rc files read/written byte-exact (non-UTF-8, CRLF); the guard can never abort a batch; an unhookable linked rc is an advisory naming what to add]
- **B14 [MED] Driver correctness batch:** native-pkg-file (removed reads installed forever; format by
  probing binaries; no non-interactive env), dnf/zypper/xbps multi-package set_version, `strip:` crash,
  dnf4 versionlock, source upgrade/archives/system scope, gem/luarocks scope + gem set-version/upgrade,
  cabal ≥3.10 XDG path, appImage/font don't require curl, `_alt._pm` sniffs the host. (drivers-os-04/05/
  07/09/10/11, drivers-lang-07..14/16, routing-13) · effort M · [open]
- **B15 [MED] Routing correctness batch:** `disabled-drivers` ignores the native manager; provider-pin on a
  capability-that-is-a-component; `{}` name-drop satisfies a hard require; partial `parts` bundles; driver
  gated by one requires ambiguity; `version-floors` changes resolution; ARM void_musl detected as glibc;
  soft pin with a failing hard requirement → error row. (routing-05..12/14) · effort M · [open]
- **B16 [MED] TUI correctness batch:** rebuild drops filter+scroll; to-do view hides non-green picks;
  pinned methods line; `handle` exceptions end the TUI; `M` moves the cursor; notes claim unchecked
  success; `--machine other` installs the other machine's picks (CLI refuses); execute skips auto-tighten;
  palette exhaustion; key-steal/shadow edge cases; `--color` on `-direct`; splash constructor crash; shared
  Resolver state written by TUI resolves. (tui-core-03..06, tui-screens-03..05, tui-theme-02/04..09,
  parity-03/09) · effort M · [open]
- **B17 [MED] Plan/ops misc:** verify-after-fail misreads reinstalls; `plugin update --ref`/`bless` report
  success on failed syncs; edits to a THIRD-PARTY manifest for transitive plugins; settings that move
  installs keep the 1-hour glue cache; theme edits land where the top config shadows them; `upgrade
  --system` failures vanish; `plugin init --dry-run` moves a tag-pinned primary; humerge keeps git's clean
  merge with a duplicate key; `x~` misread as a type change. (actions-06/08/09/10/12/13, app-cli-05/06/07/09,
  primary-04/09) · effort M · [open]

### Tier C — performance (measured)

- **C1 [HIGH] No batched candidate index for dnf/zypper/pacman/apk/brew/snap** — 100 Fedora packages: 29.5 s
  / 201 spawns vs 3.0 s batched (plus a batched held set). (drivers-os-02) · effort M · [done — Driver.latest_index (frozen hook) + the default batch_index carries candidate + held; dnf repoquery / zypper info / pacman -Si / apk list / brew info --json answer every unit in one query; dnf held_keys parses dnf4 too]
- **C2 [HIGH] Every Profiles triage key drops the resolve cache** — 0.4–4.5 s per key vs 15 ms. (tui-screens-02)
  · effort S · [done — Context.invalidate_config: picks/dispositions/uninstall/machine writers keep the Resolver; the Profiles warm cache re-warms only for the current routes]
- **C3 [MED] Re-resolution on the startup path:** `when:` grid per Resolver build (~1 s), provider index per
  resolve (81% of a single-name resolve), Resolver discarded per config edit, `diagnostics()` twice per
  inspect, Config re-merges per call (77 ms → 0.9 ms). (routing-16/17, app-cli-10/11, config-layers-09) ·
  effort M · [done — subset/witness memoized by a stable cascade fingerprint + when-text and persisted (state/grid-memo.json, never under --pretend); lineage + derivative cells cached; provider index once per component set; Config views cached per instance; diagnostics memoized; setting/theme edits invalidate only what they affect]
- **C4 [MED] Version caches:** versions.hu parsed per unit and read torn under the thread pool (2026-09
  B9); method-versions a second cache class; serial superseded-install probes; pipx N+1; manifests re-parsed
  per command. (subsystems-08/09/11, drivers-lang-15, plugins-06) · effort M · [done — one TTL cache class (cachefile.py): memoized parse, atomic save, saved only when changed (versions.hu + method-versions.hu); pipx batches interpreters, pip/pipx probes per runner; manifests + plugin identity memoized; swap planning uses the probe cache and one ledger load]
- **C5 [MED] Shell startup:** `cs_loc` linear scan + fork per call (~100 ms); cached `pyenv init` still
  rehashes (~70–110 ms). (dotfiles-glue-15/16) · effort S · [done — cs_loc is a hash lookup in bash/zsh (associative array) and fish (parallel lists, contains -i); pyenv init cached with --no-rehash (and nu)]
- **C6 [MED] TUI per-keystroke/preview:** Profiles untracked count re-merges per row; Theme previews build real
  models (`git ls-remote` per plugin); dnf reinstalls versionlock per lock. (tui-core-07/09, drivers-os-08) ·
  effort S · [done — Profiles ⊙N counts memoized per (config, profile, ceiling, overlay, probes); Theme samples build screens with load=False (no real plugin read, primary fetch or ls-remote); dnf installs versionlock only when missing]

### Tier D — refactors (each collapses a bug class)

- **D1 One settings registry** (2026-09 D5) — nine tables, twenty getters, three parsers → B11's class.
  (config-layers-20, actions-17) · effort M · [open]
- **D2 Split app.py** (D9; 35% bigger than when proposed) **and menu.py.** (app-cli-14, tui-core-10) · L · [open]
- **D3 One plan builder for CLI + TUI** (the rest of D3) — ends B1/B2/A7's divergence. (actions-15/16,
  app-cli-12/13) · effort M · [open]
- **D4 `LinkedContentDriver` + a `ShellSpec` table** (D7) — glue/dotfiles link/backup in Python, one place for
  A8/A15. (dotfiles-glue-23) · L · [open]
- **D5 Finish `ModuleDriver`** (D4) for the ten ecosystem installers; `GccToolset` onto `AltDriver`.
  (drivers-lang-17/18) · effort M · [open]
- **D6 `SelectionPolicy` + a stateless Resolver** (D6) — one caller already drops policy; TUI resolves
  overwrite shared state. (routing-18/19, tui-core-06) · effort M · [open]
- **D7 TUI view-model memo + shared chrome** — Profiles/Components paint from live models; draw writes the
  model; three hand-copied table screens; seven modal frames. (tui-screens-06..10, tui-core-08) · L · [open]
- **D8 The release registry drives derivative gates** — a derivative's `base:` lets `ubuntu >= 24.04` reach
  Zorin 18 / Mint 22 (os-releases plan phase 5); retires 31 hand-kept lists and fixes 11 wrong gates.
  (os-releases.md §3) · effort M · [done — derivative releases carry base: in the registry; versioned base atoms evaluate through it at runtime and in the static grid; 31 hand-kept derivative lists retired (equivalence-checked); check warns for an unregistered derivative release]
- **D9 A parity table that fails when a CLI verb ships without a TUI decision.** (parity-11) · S · [open]

### Tier E — docs vs code
- **E1** docs/plugins.md §6 promises vendor-source/recipe data is refused until trust — fold into A1 (code
  is wrong). (security-07) · [done 48507e9 — docs/plugins.md §6 rewritten to the enforced gate (with A1)]
- **E2** comment/docstring drift across 12 areas (retired models, deleted painters, M1 notes) — for the next
  `/update-docs --deep`. (app-cli-17, config-layers-22, dotfiles-glue-37, drivers-lang-33, routing-33,
  subsystems-14/15, tui-core-12, tui-screens-19, tui-theme-24, primary-24) · [open]

### Tier F — ABI / interface (decide before collaborators)
- **F1** Trust identity isn't length-prefixed (constructible collision) — bump with A1. (plugins-08) · [done 48507e9 — plugin_identity v2: length-prefixed, symlinks hashed as links; old-format approvals/pins still match unchanged content (with A1)]
- **F2** Retired vocabulary as live identifiers (`candidate_only` …) and positional routing returns.
  (routing-20/31/34) · [open]
- **F3** `primarygit.will_write` is required of code-plugin drivers but isn't in the frozen ABI; the splash
  ABI is re-exported as frozen but not pinned; installed-name dict form has no shared helper.
  (primary-22, tui-theme-19, drivers-os-16) · [open]
- **F4** Private reach-ins (app.py into a dozen modules; `Config._layers`; ad-hoc ctx attributes; three
  "--pretend, nothing written" conventions). (app-cli-24/29, config-layers-24, tui-core-21, tui-screens-23,
  actions-35) · [open]
- **F5** Dead public names: `errors.ResolveError`, `predicate.Cpu`, `Resolver.candidates(include_unavailable)`.
  (routing-29/30) · [open]

### Tier G — features and parity
- **G1 [MED]** TUI has no rebuild/reinstall, `set-version` or `fix-scope`; the method picker can't leave a
  component unpinned (writes a hard pin). (parity-04/05, tui-core-25) · [open]
- **G2 [MED]** `check`'s lints never reach the TUI `!` page (plugin conflicts, driver shadowing, key
  lockouts, bad setting values). (parity-06, config-layers-18) · [open]
- **G3 [MED]** TUI `plugin add` has no `--local`/ref/pin — a project path gets published to every machine;
  no `picks to-primary`; `plugin init`/`set-source` CLI-only. (parity-08/10/13, tui-screens-24) · [open]
- **G4 [LOW]** Glue verbs split between surfaces (staged glue under `dotfiles`; `glue add/override`
  CLI-only); the uninstall queue has no CLI. (dotfiles-glue-33, parity-12, actions-29, app-cli-22) · [open]
- **G5 [LOW]** Primary UX: the TUI push popup doesn't list files; `plugin undo` takes back another
  machine's change without saying so; a pushed `.hu` isn't parse-checked; signed-only push doesn't warn on
  unsigned outgoing commits. (primary-14/15/20/21) · [open]
- **G6 [LOW]** Theme lint; `keys` provenance; CLI catalog search; `--version`; the example plugin's
  README commands fail. (tui-theme-15/22, parity-18/19, app-cli-33, plugins-04) · [open]

## 4. Test gaps
Mutating key paths are untested on every TUI screen (no TUI `--pretend` sweep — tui-screens-11); verbs no
test drives through `main` (the gap that hid B1 — app-cli-15); every confirmed CRITICAL/HIGH above lacks a
regression test (each area file's "Test gaps" section lists them). tests-tools adds: host-dependent tests (real dpkg/flatpak/brew probes, api.github.com — tests-tools-04); ~55% of suite time re-parses routes.hu (0.4 s per load — tests-tools-05, a session-scoped cache); namesweep/osaudit report OK when the container never ran, compaudit turns outages into "broken" (06/07 — weigh the component audit's broken count with this in mind); podman harnesses drifted from the code (08); the golden doesn't cover two managers or the newest releases (09, with os-releases §5).

## 5. OS releases and the catalog
**OS releases** (detail: `os-releases.md`): registry for every versioned line landed the same day
(`956208e`); Fedora 46 (Rawhide) prerelease entry proposed. Broken on live releases: **EL 10 — 64 names**
missing from EPEL 10, EL 9 — 38, Leap 16 — 27, AL2023 — 27, Debian 12/13 — 11/8 (incl.
`software-properties-common` gone in trixie: `ppa:` bindings fail there), Ubuntu 26.04/26.10 — 4, Alpine
3.22/3.23 — 6/3. Derivative-vs-base drift on Zorin/Mint/elementary/LMDE/MX (→ D8). Fixtures: no golden
context for ubuntu 26.10, rhel 10, elementary 8.1. Not run: driver lifecycle harnesses, per-release repo
probes; EL 8 sweep timed out twice.

**Catalog** (detail: `components.md`; full proposed edits in the compaudit run dir): all 667 units
deep-audited — **184 broken · 163 drift · 221 opportunity · 142 note** (no GitHub token: probe-level
license/archived facts skipped). Patterns: **EPEL/EL gating (103, 69 naming EL 10)** — one release-scoped
pass with the os-releases EL 10 fix; **native names (94)** — Void `-devel` splits for lib components,
Tumbleweed's versioned packages, Amazon Linux absences; license/telemetry/attrs drift (30); vendor repos
(23). Broken findings are not yet individually re-fetched (deferred to apply, per `/update-component`).

## 6. Suggested sequencing
1. **A17 first** (so the fixes after it can't touch this machine), then **A2, A3, A4, A5, A7, B2** — small or medium, each a data-loss or surprise path in everyday use.
2. **A1** as a plan (theme 1: gate at resolution) — the one trust-boundary decision; F1 rides along.
3. **B1 + D3** together (plan builder), then **A6/A8/A9** with a shared `safe_remove` (theme 2).
4. **B3, B13** (glue loads/ordering wrong on non-Debian and fish), **B12** (EL9/AL2023 bootstrap), then the
   OS-release fixes (EL 10 first).
5. **C1, C2, C3** (perf), then the B batches and D refactors by appetite.

## 7. Decisions (2026-11-08, from you)
1. **A1 policy:** gate every command / privileged-write / download binding from an untrusted layer — not a
   candidate until `plugin trust` (an "untrusted" row says why). Downloads are not "inert".
2. **A1 severity:** CRITICAL.
3. **Plugins `x` / `t` / `T` / `b`:** keep one-key for now. (So A3 becomes: refuse when the clone holds
   unpushed or uncommitted work, naming it, unless `--force`; no popup.)
4. **D8:** registry-driven. Derivative releases carry `base: "<line> <version>"`; a versioned base atom
   (`ubuntu >= 24.04`) evaluates through it; the hand-kept derivative lists retire. A derivative release
   missing from the registry reads as an unknown version (versioned atoms false) with a `check` warning.
5. **A11:** every key stays rebindable; a plugin's `keys:` are honored only when that plugin is trusted
   (keys become executable-ish data: `ships_executable_data` covers them). Repo + top config always.
6. **Primary trust:** a new top-config-only setting `primary-trust: identity | content | signed`,
   **default `identity`** (whatever syncs into the primary is trusted); `content` = today's re-trust on
   change; `signed` = identity only when the commits verify, else content.
7. **B3:** bash like zsh — one configsys block in `~/.bashrc` sourcing `conf.d`; `.bashrc` created where
   absent (and a `.bash_profile` that sources it where neither profile exists); the `~/.bash_aliases` link
   retired; `_loader_ok` verifies the chain.
8. **Locks:** an explicit op on a locked component refuses ("locked at X — unlock first"); bulk U/I and
   `--picks` skip locked; `set-version` allowed and re-locks at the new version; `remove` clears the lock;
   a lock follows the component across a method swap.
9. **Dependencies:** CLI and TUI both install only missing dependencies (upgrade touches only the named
   component); CLI `--with-deps` re-runs the tree; `--no-deps` = not even missing ones.
10. **Transitive plugins:** keep the open fan-out; surface the chain (who declared whom) in `plugin list`,
    the Plugins screen and `check`.
11. **Source trees configsys didn't create:** refuse unless adopted (an explicit adopt marks it); `remove`
    never deletes a tree configsys didn't clone (it reports it).
12. **Preference knobs:** a plugin's `driver-preference:` counts only on os blocks that plugin defines;
    elsewhere (and `drivers:` `standing:`/`when:` from non-primary plugins) ignored with a `check` warning.
13. **Key precedence:** a higher layer's global/screens binding takes the key from a lower layer's page
    binding; within one layer page beats global; `check` reports each steal.
14. **Layer-grouped Profiles list:** deleted (with its ceiling plumbing). **Splits:** app.py → per-command
    modules that own their argparse slice (a registration table); menu.py → screens / modals modules.
15. **Dotfiles "move to local":** copies — the primary keeps it for other machines.
16. **Legacy migration shims** (old staged-glue layout, pre-band links, `bash.d`): retired.
17. **TUI set-version / rebuild:** rows in the `v` picker ("pin version…", "rebuild", "auto — unpin").
18. **Theme load:** overlays the pack under your overrides; "reset to pack" is separate, confirmed.
19. **Bare `plugin trust`:** lists each untrusted plugin with what it ships and asks y/N on a tty;
    `--all --yes` for scripts; refuses unattended.

**Defaulted (the area files' remaining questions — say if you disagree):** `machine:` and `uninstall:`
top-config-only · plugin/primary `include:` confined to its own tree · the shell-writes guard skips the
dotfiles/glue drivers and refuses to write through a link whose identity changed · dotfiles uninstall
restores the oldest backup only when the target is still our link, and reports the rest · `--home` is a
full sandbox (children get `HOME=<sandbox>`; inherited `CONFIGSYS_STATE_DIR`/`CONFIGSYS_CONFIG` dropped) ·
gem `set-version` removes the other versions (the plan says so) · version-less source recipes fast-forward
on upgrade and report the remote tip · batched candidate index as a `NativePkgManager` hook (ABI addition)
· `installed_name` promoted now · TUI `--machine <other>`: Components read-only with a banner · `check` lints
reach `!` on a background thread · TUI `plugin add` of a local path defaults to this machine only ·
example plugin README fixed with the batch · locked primary: push refuses to combine (pushes only when not
behind) · ignored file the remote now tracks: stop and ask · undo of a move-in commit saves the files to
`<state>/undo/<sha>/` first · undo of another machine's change says so and confirms · "don't push" after a
combine puts HEAD back · duplicate keys flagged by `check`/`!` · a bundle part with no route here is skipped
with a notice · specificity over minimal elements (principles.md; routing-model aligned) · a `{}` name-drop
fails a hard requirement · `version-floors` affects resolution at both levels · `disabled-drivers: [apt]`
disables `via: native` reaching apt · version `url:` https-only and trust-gated · decode-error re-run fixed
regardless · bulk sudo paths through `sudo_session` · hermetic conftest by default (real-tool tests opt in
by marker) · golden keeps EOL contexts frozen · runner-less integration scripts get runners · component
rows act on their own units; a profile row's `x` means everything under it · to-do view shows `error` /
`untrusted` picks · `v` picker "auto — unpin" · resolver-irrelevant TUI writes invalidate only the config ·
draw never writes the model (a layout step; tested) · `theme:` from any layer (cosmetic) · `NO_COLOR` yields
to an explicit `--color` (no-color.org) · splash under `NO_COLOR`/`--effects none` = the plain progress bar
(docs fixed) · splash ABI frozen now (with `depth`) · settings registry (D1) in scope · System Updates: a `!`
note when the OS's own manager can't list.
