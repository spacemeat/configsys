# lazygit: alias to the tarball-installed binary (on fedora/arch it's native on PATH, so this
# no-ops there). configsys unpacks the tarball under ~/apps/lazygit (or /opt/apps/lazygit).
for _lg in "$HOME/apps/lazygit/lazygit" /opt/apps/lazygit/lazygit; do
    [ -x "$_lg" ] && { alias lazygit="$_lg"; break; }
done
unset _lg
