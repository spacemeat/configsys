# android-studio: alias `studio` to the tarball-installed launcher. Newer Studio ships
# bin/studio; older bin/studio.sh -- prefer whichever exists. No-ops if not managed here.
_as=$(configsys location android-studio 2>/dev/null)
if [ -n "$_as" ]; then
    for _c in "$_as/bin/studio" "$_as/bin/studio.sh"; do
        [ -x "$_c" ] && { alias android-studio="$_c"; alias studio="$_c"; break; }
    done
    unset _c
fi
unset _as
