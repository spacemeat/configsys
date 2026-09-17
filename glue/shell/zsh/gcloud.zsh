# gcloud: the Google Cloud SDK installs to ~/google-cloud-sdk (off PATH). Source its PATH +
# zsh-completion shims when present. No-ops where gcloud is otherwise on PATH.
_gc=$(configsys location gcloud 2>/dev/null)
if [ -n "$_gc" ]; then
    _gcroot=$(dirname "$_gc")
    [ -f "$_gcroot/path.zsh.inc" ] && source "$_gcroot/path.zsh.inc"
    [ -f "$_gcroot/completion.zsh.inc" ] && source "$_gcroot/completion.zsh.inc"
    unset _gcroot
fi
unset _gc
