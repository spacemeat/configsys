# Community routes registry — design note

**Status:** design only, NOT scheduled. Captures the analysis of "let anyone contribute routes so
configsys covers far more than we could ever route by hand." The conclusion is a *curated + federated*
design, explicitly **not** a live central registry. Written 2026-09-23.

## The idea (and the real motivation)

However many components we route by hand, the long tail is unbounded (Nix hosts ~140k packages;
people use all sorts). Routes are **data**, not code — so in principle the community could fill in
routes en masse and configsys could reach ~90% coverage without us authoring every one.

This is architecturally natural because **the substrate already exists**: the layer stack
(repo < plugins < primary < user), the plugin model with **content-hash trust**, ABI versioning,
sha256 checksum verify + quarantine, per-source pinning, and — the underrated piece — strong
**machine-verifiable validation** (`check`, namesweep across every package manager, resolve sweeps,
the golden gate, the podman real-install lifecycle). "Share routes" is already possible today via
plugins. So the real question is **what shape** the sharing takes.

## The load-bearing correction: "data, not script" is NOT a security boundary

The tempting safety claim is "routes are data, so a routes registry is safe." **It isn't**, on its
own. A route's whole purpose is to name **what gets installed and from where**, and installing is
inherently privileged. Pure "data" can already:

- `tarball` / `appImage` / `native-pkg-file`: carry a **URL** → point it at a hostile payload; a
  malicious `.deb`/`.rpm` runs maintainer scripts **as root**. RCE via data.
- `native`: name a **package** → a typosquat, or a binding that adds an attacker's apt repo + key.
  RCE via data.
- `script` / `source`: literally carry **commands / build recipes**. Script wearing a data costume.

So a public-editable routes source is a **supply-chain redirect surface** — the same problem AUR,
npm, PyPI, and Nix all fight and none has "solved." The "no scripts in the configsys process" rule
usefully shrinks the in-process attack surface, but it does not make the *downstream install* safe.

### Risk is tiered by driver — this is the key to making a registry safe

| tier | drivers / shapes | why | vetting |
|------|------------------|-----|---------|
| **T0 low** | `native` → a **distro-standard** repo | trust delegated to the OS repo (already trusted); the only claim is "the package is named X", which is **machine-verifiable** (namesweep already checks this) | auto |
| **T1 medium** | `flatpak`/`snap` (Flathub/Snap Store app ids) | delegated to a curated hub; app id verifiable | auto + light |
| **T2 high** | `tarball`, `appImage`, `native-pkg-file`, vendor-repo `native` (adds a repo/key), language-module drivers | the route **is** the supply chain: URLs, third-party repos, keys | human review + checksum/signature required |
| **T3 highest** | `script`, `source` (`build:`, `install-cmd`) | commands / build recipes = code | human review; maybe disallowed in the community tier entirely |

The safe **bulk** (T0/T1) is auto-verifiable; the dangerous **tail** (T2/T3) needs review and signing.
A community registry is tractable precisely because it can *tier* and treat these differently.

## What to build — and what to never build

**Never build:** an online resource anybody can edit that configsys **auto-pulls live**. That is a
single point of compromise for every user, unbounded moderation load, a permanent attack target, and
an operational/funding/governance commitment of a completely different species than a CLI. This is the
"lumbering, untrustable" project the gut rightly fears.

**Do build (if demand proves out), in increasing commitment:**

### Phase 0 — plugin catalog / index (near-zero liability, tests demand)
A directory of known route **plugins**: what each covers, who maintains it, its ABI, trust status.
Ships as data (a `.hu` index in-repo or a small static site generated from it) + `configsys plugin
search`/`browse`. No new hosting, no moderation of *content* (just a curated list of *sources*). This
is the existing "known plugins list" open item, promoted to a feature. **It answers "is the demand
real?" before any heavier commitment**, and it already delivers discoverability — the main thing a
central registry would add over today's federation.

### Phase 1 — a curated `configsys-community-routes` repo (the homebrew-core model)
A single community routes repo, contributions by **PR**, with **CI = your existing validation** run
automatically:
- **auto-reject** on: doesn't parse / `check` errors / names a nonexistent native package (namesweep)
  / fails to resolve on the claimed OSes / perturbs the golden gate / raises warning count.
- **tier gate:** T0/T1 PRs that pass CI are (near-)auto-mergeable; **T2/T3 require human review** +
  a checksum (and, when available, a GPG signature — on the roadmap) for every off-repo asset.
- **released as pinned tags**, never a live HEAD. Users add it like any plugin and **pin to a
  reviewed release**; content-hash trust (already built) means "I trust this reviewed snapshot", not
  "I trust whatever a stranger typed 30 seconds ago."

This is the actual moat: **because routes are machine-verifiable data, most quality AND much of the
security gating is automatable.** A crowdsourced *code* registry (AUR) can't do this; a crowdsourced
*route* registry can. The excitement belongs here — not to "crowdsourcing" but to "crowdsourcing a
format a machine can largely vet."

### Phase 2 — federation stays the long tail
Niche / personal / experimental / T3 routes stay as ordinary **plugins**, explicitly per-source
trusted, exactly as now. The curated repo is the reviewed core; plugins are the taps.

## Precedents (they all tier; none merges trusted-core with open-crowd into one live pool)
- **AUR** — user PKGBUILDs, explicitly *untrusted*, norm "read it before you build". (Our data model
  beats arbitrary bash, but is not immune — see T2/T3.)
- **NUR** (Nix User Repository) — the crowd tier kept explicitly at arm's length from trusted
  Nixpkgs, "use at your own risk".
- **Homebrew** — reviewed + CI'd `core`; federated `taps` for the tail.
- **Flathub** — reviewed, with a **verified** badge for first-party publishers.

## Sustainability — the honest read
- A **hosted service** = funding, moderation, governance, becoming a target; many such projects die or
  become liabilities. Avoid.
- A **git repo + PR review + CI** = leverages GitHub + our existing tooling; its main cost (review
  time) scales *with* popularity (the good kind of problem) and is distributable across maintainers.
  This is the sustainable vehicle.

## Non-goals
- No live/auto-pulled central registry; no following a public HEAD.
- No storefront/discovery-of-arbitrary-apps beyond a catalog of *sources*.
- No hosting of the actual packages — we route to existing distribution; we never become a mirror.
- Not a replacement for distro trust — T0 routes *delegate* to the OS repo on purpose.

## Open questions (for whenever this is picked up)
- **Signing/provenance for T2/T3 assets** — checksum is here; GPG sig verify is roadmap; do we require
  a signed asset manifest per off-repo route? Sigstore/cosign for tarballs?
- **Reputation / maintainer identity** — per-route `maintainer:` + a trust ladder (verified
  publisher), or keep it flat + review-only?
- **Vendor-repo `native` routes** — these add a third-party repo+key (real T2 risk) yet look like
  cheap `native`. CI can't fully vet an added repo; treat any repo/key-adding `native` as T2.
- **Curated-repo governance** — who merges T2/T3? A small maintainer set + CODEOWNERS by tier.
- **Dedup / canonicalization** — one canonical route per tool in the curated repo vs. N plugins each
  redefining it (layer merge already handles overlap, but a canonical source reduces confusion).
- **Revocation** — if a released route is later found malicious, how do pinned users learn? A
  signed revocation list configsys checks (ties to the plugin trust model).
