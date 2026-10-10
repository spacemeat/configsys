# cliamp: alias to the tarball-installed binary wherever configsys unpacked it (the binary sits
# inside the install dir). No-ops where cliamp is native on PATH.
_cli=$(cs_loc cliamp)
[ -n "$_cli" ] && [ -x "$_cli/cliamp" ] && alias cliamp="$_cli/cliamp"
unset _cli
