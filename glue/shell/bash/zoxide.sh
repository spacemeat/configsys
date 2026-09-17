# zoxide — a smarter cd. Registers the `z` / `zi` commands on shell start.
if command -v zoxide >/dev/null 2>&1; then
    eval "$(zoxide init bash)"
    # Old zoxide (<~0.5, e.g. Ubuntu/Pop 22.04's 0.4.3) shipped a PROMPT_COMMAND hook whose bare
    # if/elif has no else, so it returns 0 UNCONDITIONALLY — clobbering $? for a status-colored
    # prompt (a red/green last-exit indicator would always show green). Wrap the hook so it
    # preserves the exit code. Harmless on modern zoxide (its hook already does `local -r retval=$?
    # … return "$retval"`); covers both the old (`_zoxide_hook`) and new (`__zoxide_hook`) names.
    for _cfs_zh in __zoxide_hook _zoxide_hook; do
        declare -F "$_cfs_zh" >/dev/null 2>&1 || continue
        eval "__cfs_z_$_cfs_zh() $(declare -f "$_cfs_zh" | tail -n +2)"
        eval "$_cfs_zh() { local __cfs_r=\$?; __cfs_z_$_cfs_zh; return \$__cfs_r; }"
    done
    unset _cfs_zh
fi
