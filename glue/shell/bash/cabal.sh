# cabal: put cabal-installed executables (hlint, etc.) on PATH.
for _d in "$HOME/.cabal/bin" "$HOME/.local/bin"; do
    [ -d "$_d" ] && case ":$PATH:" in *":$_d:"*) ;; *) PATH="$PATH:$_d" ;; esac
done
unset _d
export PATH
