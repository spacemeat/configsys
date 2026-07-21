#!/usr/bin/env bash
# Runs INSIDE an EL9 (AlmaLinux/Rocky) container as `tester`. Proves the EL multimedia
# story end to end through the real configsys entry point:
#   - ffmpeg: `install` pulls rpmfusion-free, which enables EPEL + CRB and drops the
#     RPM Fusion free repo, after which ffmpeg (absent from base AND EPEL) installs.
#   - vlc:    EL carries it in EPEL (not RPM Fusion) — the `when: rhel requires: epel` edge.
#   - kicad:  not packaged for EL9 anywhere — configsys must decline cleanly (unroutable),
#             never attempt a doomed `dnf install`.
# Asserts against rpm / dnf directly. Needs network (downloads RPM Fusion + EPEL).
set -euo pipefail

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

. /etc/os-release
say "target: $PRETTY_NAME (ID=$ID) -> rhel block"
printf '{ configs: user }\n' > "$HOME/configsys.hu"

say "precondition: ffmpeg absent, RPM Fusion not set up"
rpm -q ffmpeg >/dev/null 2>&1 && fail "ffmpeg already installed"

say "install ffmpeg via configsys (rpmfusion-free -> EPEL + CRB + repo, then ffmpeg)"
bash configsys.sh install ffmpeg
rpm -q epel-release >/dev/null 2>&1          || fail "epel-release not installed (EPEL edge)"
rpm -q rpmfusion-free-release >/dev/null 2>&1 || fail "rpmfusion-free-release not installed"
dnf repolist --enabled 2>/dev/null | grep -iq crb || fail "CRB not enabled (needed for ffmpeg deps)"
rpm -q ffmpeg >/dev/null 2>&1                || fail "ffmpeg not installed"
echo "  ffmpeg $(rpm -q --qf '%{VERSION}' ffmpeg) from RPM Fusion"

say "install vlc via configsys (EL path: EPEL, not RPM Fusion)"
bash configsys.sh install vlc
rpm -q vlc >/dev/null 2>&1 || fail "vlc not installed (EPEL)"
echo "  vlc $(rpm -q --qf '%{VERSION}' vlc) from EPEL"

say "kicad is unroutable on EL9 — configsys must decline, not attempt dnf"
out="$(bash configsys.sh install kicad 2>&1 || true)"
echo "$out" | grep -qi 'No match for argument' && fail "kicad attempted a doomed dnf install (should be unroutable)"
rpm -q kicad >/dev/null 2>&1 && fail "kicad somehow installed on EL"
echo "  kicad declined cleanly (unroutable on EL)"

say "remove ffmpeg + vlc via configsys"
bash configsys.sh remove ffmpeg
bash configsys.sh remove vlc
rpm -q ffmpeg >/dev/null 2>&1 && fail "ffmpeg still installed after remove"
rpm -q vlc >/dev/null 2>&1 && fail "vlc still installed after remove"

printf '\nPASS: EL RPM Fusion (ffmpeg) + EPEL (vlc) + kicad-unroutable via configsys on %s\n' "$ID"
