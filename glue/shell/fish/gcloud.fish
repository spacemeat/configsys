# gcloud: source the Cloud SDK's fish PATH + (interactive) completion shims when present. No-op where otherwise on PATH.
set -l loc (cs_loc gcloud)
if test -n "$loc"
    set -l root (dirname "$loc")
    test -f "$root/path.fish.inc"; and source "$root/path.fish.inc"
    status is-interactive; and test -f "$root/completion.fish.inc"; and source "$root/completion.fish.inc"
end
