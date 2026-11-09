# zoxide — a smarter cd. Registers the `z` / `zi` commands on (interactive) shell start.
status is-interactive; and command -v zoxide >/dev/null 2>&1; and zoxide init fish | source
