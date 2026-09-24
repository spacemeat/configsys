# configsys — principles

The load-bearing, cross-cutting rules this project keeps returning to. They outrank convenience;
break one only with a deliberate, recorded reason. (The routing spec proper is
`docs/routing-model.md`; this is the shorter "why we decide things this way" list.)

## Safety

- **Never `rm` a path derived from `$HOME`** — even a reassigned `$HOME`. A test/sandbox home that
  gets emptied by a driver's uninstall is how the tarball `rm -rf $HOME` bug happened (fixed
  fcafb84). Use literal scratchpad paths; pass an explicit inline `HOME` to sandboxed subprocesses
  rather than trusting the ambient one.
- **Validate before you commit an OS-level change.** A vendor apt source / key is written, then
  verified, and rolled back if it broke `apt-get update` — never leave a poison pill that bricks
  every later op. Same posture for any driver mutation: no half-applied state that wedges the next run.
- **Read the target before deleting or overwriting it**, and confirm hard-to-reverse or
  outward-facing actions unless already authorized.

## Working relationship

- **Never `git push` for the user.** Commit locally only, and only when asked; they decide what
  leaves the machine.
- **No surprises.** The user should always know what is installed, what an operation *will* change
  before it runs (preview first), and what is deliberately left alone. Don't auto-do the clever
  thing silently — surface it and let them choose.

## Routing / capability model

- **`via` = mechanism identity.** One driver per genuine install mechanism. A method that rides a
  different update path or artifact source is its own `via` (e.g. `native-pkg-file` ≠ repo
  `native`), not a flag on another.
- **`when:` states VALIDITY, never preference.** It answers "does this method work *here*?" Choice
  among valid methods is decided by specificity → `standing` (the one author preference knob) →
  `driver-preference` (the machine setting) — never by `when:`.
- **Specificity first, then the one knob.** A more-specific `when:` beats a broader one before any
  preference is consulted. `standing` is the *only* preference control (it replaced
  `prefer:`/`candidate-only:`/`opt-in:`).
- **Offer every working method; auto-pick conservatively.** Broadening the *listed* methods (so the
  user can pin any that works here) is safe when the added ones aren't in the default
  driver-preference — validity ≠ becoming the default.
- **Detection-first for what's already installed.** An installed provider/method is adopted over the
  bare default (precedence: pin > detected > standing default), so we manage reality, not fight it.
- **Switching a method removes the old install first** — never double up the same capability across
  two mechanisms.
- **Requires is HARD, suggests is SOFT.** An unmet require is an error; an unmet suggest is skipped
  silently. Version floors are *floors only*, surfaced-and-chosen, not silently auto-bumped.

## What we deliberately do NOT model

- **cfs does not model base-OS vs dependency.** The package manager on the box is the version-correct
  authority; cfs asks it "what's installed / upgradable?" and drives *its* bulk commands. No authored
  per-(distro×version) base manifests — they'd be a staler duplicate and break on rolling distros.
- **Components and System Updates may overlap harmlessly.** A component is for something the user
  *wants* to manage (pick, version, pin); System Updates patches the whole machine so the user is
  never *forced* to manage base packages/deps. A thing can be both — the update lane just de-duplicates
  the display (hides things cfs already knows as an installed component), and the bulk `apt upgrade`
  patches them regardless. So "should X be a component?" is answered by "would a user deliberately
  manage X?", never by whether updates already cover it.
- **"Data, not script" is not a security boundary.** Route/plugin *data* can still drive shell
  (source builds, scripts), so trust is gated by content-hash + risk tier by driver, not by
  file extension. Never a live-central registry.

## Hard-won implementation lessons

- **Tile by surface accretion, not by placing arbitrary shapes** (blocks splash): fill the lowest
  column and only add supported cells → generation order *is* a valid gravity drop order, with no
  holes and no mutual-support deadlock.
- **Build the path first, grow structure around it** (maze splash): the head follows a precomputed
  route = progress, so no runtime physics is needed to guarantee a solvable/animatable result.
- **A pty is a different controlling terminal.** Under sudo `tty_tickets`, capturing through a pty
  re-prompts every op; pre-auth on the *real* tty once per batch instead (sudo-tty fix).
