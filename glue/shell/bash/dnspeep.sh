# dnspeep: alias to the tarball-installed binary (upstream ships a single `dnspeep` in the tar).
# Run it with sudo (it sniffs DNS via libpcap). No-ops if dnspeep isn't managed here.
_dp=$(cs_loc dnspeep)
[ -n "$_dp" ] && [ -x "$_dp/dnspeep" ] && alias dnspeep="$_dp/dnspeep"
unset _dp
