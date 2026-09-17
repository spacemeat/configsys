# gcloud: source the Cloud SDK's fish PATH + completion shims when present. No-op where otherwise on PATH.
set -l loc (configsys location gcloud 2>/dev/null)
if test -n "$loc"
    set -l root (dirname "$loc")
    test -f "$root/path.fish.inc"; and source "$root/path.fish.inc"
    test -f "$root/completion.fish.inc"; and source "$root/completion.fish.inc"
end
