# apod: splat NASA's Astronomy Picture of the Day (termapod) on interactive shell startup. Guarded on
# an interactive shell so it never dumps an image into a script / scp / non-interactive ssh command.
# It's a network fetch at shell startup, so it's CAPPED (8s) and a failure is ONE quiet line, never a
# traceback (e.g. 2026-09: apod.nasa.gov served a cert for the wrong host, so every fetch failed).
# No-op until apod (termapod) is installed.
if (has-external termapod) {
  try {
    if (has-external timeout) { timeout 8 termapod 2>/dev/null } else { termapod 2>/dev/null }
  } catch {
    echo "apod: no picture today — NASA's APOD site is unreachable or erroring (run termapod to see why)" >&2
  }
}
