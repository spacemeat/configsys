# Offer every working method — a `when:`-is-validity audit

Status: **PHASE 1 DONE** (commit follows this doc). Phase 2 (add *missing* universal methods per a
registry-existence sweep) is still pending. Phase-1 result: the 18 gap-gated bindings below were
broadened to universal validity — golden moved by exactly ONE new resolution (`qtile` now resolves on
`fedora_atomic` via pipx, a newly-covered gap); NO existing default moved; 0 check errors / no ties
across pop/fedora/arch/alpine/opensuse/rhel/fedora_atomic/amzn; full suite green. The real wins live
off the golden's context set (cargo now offered/pinnable on amzn+atomic for dysk/pastel/fd/bat/…,
which previously declined there entirely).
Goal: stop artificially restricting install methods. If a method *works* on a machine, it should be
*offered* there (listed + pinnable) — even when it isn't the default. The user keeps control by
pinning. Scope: every non-source method (cargo, flatpak, pipx, npm, go-install, gem, snap, …).
**`via: source` (the configsys-source build recipes) is explicitly DEFERRED** to a later pass.

Prompted by `zoxide`, whose `cargo` binding was gated `when: "amzn"` — but the crate builds anywhere
cargo runs, so gating it to Amazon needlessly hid a valid option everywhere else. That was fixed
(commit a72362e) to a plain `via: cargo`; this plan generalizes that fix across the catalog.

## The principle (already in the routing model — we just weren't applying it)

`when:` states **VALIDITY ONLY** — *does this method work here* — never preference. Which valid
method becomes the **default** is decided elsewhere: `standing:` (author knob) → `driver-preference`
(machine order). Narrowing `when:` to force a default (or to "tidy" the option list) is the
anti-pattern: it deletes a working option the user can no longer pin.

The gap-filler idiom `native … / cargo when: "not (arch or …)"` is exactly this mistake: it makes
cargo the default *in the gap*, but a non-candidate everywhere native exists — so a Debian user who
wants the newer crate build can't pin it. The fix: make cargo valid **everywhere it works**; the
default doesn't change (see below), the user just gains the option.

## Why broadening is safe (the resolution mechanics)

`configsys/resolve.py:94`:
```
DEFAULT_DRIVER_PREFERENCE = ['native','flatpak','snap','native-pkg-file','appImage','tarball','source','script']
```
and `:92`: **"drivers absent from the list are least-preferred and tie among themselves (a tie is an
error)."** The module installers — **cargo, pipx, npm, go-install, gem, opam, luarocks, cabal** — are
NOT in the list. Consequences:

- Broadening ONE gap-gated module-installer to universal validity **does not change any default**:
  where a listed method (native/flatpak/…) is valid it still wins; in the gap the module-installer is
  still the sole candidate. It merely *also becomes a candidate* where native exists → **pinnable**.
- **Invariant (the one real risk):** never make TWO not-listed vias simultaneously valid for one
  component without a `standing:` tiebreaker — that's a resolve-time tie ERROR (and a `check`
  warning). Broadening a *single existing* gap method never trips this; **adding** a second one
  (Phase 2) must add `standing:` (integer rank, or `never-auto`).
- Confirmed empirically by the zoxide change: `zoxide` now has native (default everywhere it's
  packaged) + universal cargo (pinnable everywhere, default only on Amazon) with no ambiguity.
- Golden: the *resolved unit* is unchanged (native still wins), so `routing_golden.json` should be
  untouched by pure broadening — verify per batch; a change there means a default actually moved.

## Method-validity reference (the CORRECT `when:` domain for each)

| via | Valid where | Notes for `when:` |
|-----|-------------|-------------------|
| cargo | any Linux — rust installs everywhere (`requires: cargo` pulls it) | universal; crate must exist; COMPILES (toolchain + time + MSRV) |
| go-install | any Linux — go installs everywhere | universal; COMPILES; go.mod floors apply |
| pipx | everywhere (python3 guaranteed) | universal; package on PyPI |
| npm | anywhere node runs | universal where node; package on npm |
| gem / opam / luarocks / cabal | anywhere their toolchain runs | universal-ish; package in the registry |
| flatpak | any Linux with flatpak (glibc desktops + atomic) | broad; the universal GUI method + only method on atomic; app on Flathub. Already in-list (rank 1). |
| snap | any distro with snapd | broad; already `standing: never-auto` globally in the `drivers:` block |
| appImage | glibc Linux + libfuse2 (NOT musl/Alpine) | `requires: libfuse2`; exclude alpine |
| tarball | glibc (or a musl asset) Linux | broad; give Alpine a musl asset or gate `not alpine` |
| native-pkg-file | the .deb/.rpm/pkg families | deb/rpm/arch only |
| native | the OS's package manager | per-OS `name:` map; genuinely OS-specific |
| **aur** | **Arch only** | GENUINELY restricted — aur *is* Arch. LEAVE gated `when: "arch"`. |

## Phase 1 — broaden EXISTING gap-gated methods (mechanical, low-risk)

Widen each of these from `when: "not (…)"` (or a narrow single-OS gate) to universal validity, keeping
any real `requires:`. Native/listed methods stay the default; the module-installer becomes pinnable
everywhere and remains the gap default. Concrete list from the survey (routes.hu):

**cargo (11 gated):** `fd-find`(fd), `pastel`, `dysk`, `bat`, `hyperfine`, `alacritty`,
`wl-screenrec`, `impala`, `bluetui`, `wiremix`, `caligula`.
 - Keep the build `requires:` where present (wl-screenrec: ffmpeg-dev/libdrm-dev/pkg-config;
   wiremix: pipewire-dev/pkg-config) — those are real, and they correctly make cargo decline where
   the dev libs are absent (that IS validity).
 - `fd-find`/`bat`: crate names differ from the binary — keep the `name:` (`fd-find`, `bat`) and the
   glue alias (`fdfind`→`fd`, `batcat`→`bat`).

**go-install (3 gated):** `hey`(rakyll/hey), `mpd-mpris`, `discordo`. Go installs everywhere; drop the
`not (arch/…)` gate (AUR/native stays default where it exists).

**pipx (2 to broaden):** `breezy`, `qtile`. (Leave `mitmproxy`'s debian pipx binding — that's a
python-version pin, `python3.13`, not an artificial OS gate; and it already offers flatpak too.)

**npm (1):** `homebridge` (`when: "not debian"` → universal where node).

**luarocks (1):** `fennel` (`when: "not (fedora/arch/alpine/atomic)"` → universal).

### Phase-1 NON-candidates (the gate encodes a real thing — LEAVE them)
- `flutter` **snap** `when: "ubuntu"` + `classic: true` — snap *classic* confinement is a
  Canonical/Ubuntu mechanism; not portable as-is.
- `kicad` **flatpak** `when: fedora_atomic` — a deliberate *specificity* trick so flatpak out-ranks
  brew on atomic (preference via `when:` specificity, intentional).
- Any `when:` with a **version bound** (e.g. `ubuntu < 24.04`, `debian < 13`) — that's a genuine
  validity floor (a feature/dep threshold), not an OS gate. Keep.
- `aur` bindings — Arch-only by nature.

## Phase 2 — ADD missing universal methods (research-heavy; later batches)

Scale: ~370 components have a single `via: native` binding. Many could also offer a universal method
they simply don't list yet. Per component, check the registry and add if present:

- **Rust tool** not offering cargo → add `{ via: cargo name: <crate> }` (check crates.io; note
  binary≠crate cases). If it also has a tarball/appImage etc., mind the tie invariant.
- **Flathub GUI app** offering only native → add `{ via: flatpak hub: flathub app: <id> }` (verify the
  app-id on Flathub — exact or it fails silently). flatpak is in-list after native, so native stays
  default; flatpak becomes the universal alt (and the atomic path).
- **PyPI CLI** native-only → add `{ via: pipx name: <dist> }`.
- **npm/gem/…** analogues.

**Guardrails for Phase 2:**
- The **tie invariant**: adding a second not-listed via (e.g. a component that would then have both
  cargo AND go-install, or cargo AND npm) REQUIRES a `standing:` on one (integer rank or `never-auto`)
  or `check` will flag an ambiguity. Prefer `never-auto` on the "opt-in" method so it's offered but
  never auto-wins.
- **Existence must be verified per registry** — the podman **name-sweep only covers NATIVE package
  names**, not crates/pypi/npm/Flathub ids. A wrong crate/app-id fails at install (flatpak silently).
  So Phase-2 additions need a crates.io / pypi / Flathub / npm check each (a scriptable sweep worth
  building: `cargo search`, `pip index`, the Flathub API, `npm view`).
- **Compile cost**: cargo/go-install COMPILE — offering them everywhere means a pin can pull a whole
  toolchain and take minutes. That's the user's informed choice (control), but keep them non-default
  (they already are: not in the preference list) so nobody eats a surprise Rust build.

## Rollout

1. **P1 batch** — mechanically broaden the ~18 gap-gated bindings above. Run `check` across the OS
   spread (0 new errors, warnings flat), regen golden and confirm it's UNCHANGED (defaults didn't
   move; if golden moves, a default flipped — investigate), full suite. One commit.
2. **P2 by ecosystem** — cargo-add sweep, then flatpak-add sweep, then pipx/npm — each a batch with
   its own registry-existence check + the tie-invariant guard. `standing:` where a second method lands.
3. **A registry-existence sweep tool** (parallel to `tools/namesweep.py`) so P2 additions are verified,
   not guessed — this is the durable piece that makes "offer every method" maintainable.

## Open questions (for when we build it)
- Default `never-auto` for cargo/go-install everywhere, so they're *always* offered but *never* auto
  the default even in a native gap? (Today the gap has no native, so the module method is the sole
  option and SHOULD default — `never-auto` would make those components unroutable in the gap. So: NO
  blanket never-auto; keep them plain, let driver-preference + sole-candidate decide. Revisit only if
  a gap ever has two module methods.)
- Should `check` gain a lint that flags a *narrow* `when:` on a module-installer as a probable
  artificial restriction (advisory), to catch regressions of this exact anti-pattern?
