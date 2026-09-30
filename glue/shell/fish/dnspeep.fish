# dnspeep: alias to the tarball-installed binary. No-ops where native / not managed here.
set -l loc (cs_loc dnspeep)
test -n "$loc"; and test -x "$loc/dnspeep"; and alias dnspeep "$loc/dnspeep"
