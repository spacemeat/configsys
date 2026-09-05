# zoxide — a smarter cd. Registers the `z` / `zi` commands on shell start.
# zoxide's zsh hook preserves $? on its own (no bash if/elif quirk), so no wrapping is needed here.
command -v zoxide >/dev/null 2>&1 && eval "$(zoxide init zsh)"
