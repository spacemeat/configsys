# gcloud: the Google Cloud SDK installs to ~/google-cloud-sdk (off PATH). Source its PATH +
# bash-completion shims when present. No-ops where gcloud is otherwise on PATH.
_gc=$(configsys location gcloud 2>/dev/null)
if [ -n "$_gc" ]; then
    _gcroot=$(dirname "$_gc")
    [ -f "$_gcroot/path.bash.inc" ] && . "$_gcroot/path.bash.inc"
    [ -f "$_gcroot/completion.bash.inc" ] && . "$_gcroot/completion.bash.inc"
    unset _gcroot
fi
unset _gc
