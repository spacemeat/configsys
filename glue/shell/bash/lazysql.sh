# lazysql: alias to the tarball-installed binary (the only install method). No-ops if not
# managed here.
_ls=$(cs_loc lazysql)
[ -n "$_ls" ] && [ -x "$_ls/lazysql" ] && alias lazysql="$_ls/lazysql"
unset _ls
