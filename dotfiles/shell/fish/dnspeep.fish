# dnspeep: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (configsys location dnspeep 2>/dev/null)
test -n "$loc"; and test -x "$loc/dnspeep"; and alias dnspeep "$loc/dnspeep"
