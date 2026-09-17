# elm: alias to the tarball-installed binary (elm/compiler ships a single gzipped glibc binary,
# gunzipped to `elm` in the managed install dir). No-ops if elm isn't managed here.
_elm=$(configsys location elm 2>/dev/null)
[ -n "$_elm" ] && [ -x "$_elm/elm" ] && alias elm="$_elm/elm"
unset _elm
