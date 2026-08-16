# Odin: tarball unpacks under the app dir (root or a versioned subdir; no-op when native).
_od=$(configsys location odin 2>/dev/null)
if [ -n "$_od" ]; then
    _ob=$(ls -d "$_od"/odin-linux-*/ 2>/dev/null | tail -1)
    if [ -n "$_ob" ]; then export PATH="$_ob:$PATH"; elif [ -x "$_od/odin" ]; then export PATH="$_od:$PATH"; fi
    unset _ob
fi
unset _od
