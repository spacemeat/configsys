# julia: add the tarball-installed Julia's bin to PATH (unpacks into julia-<ver>/bin). No-op
# where julia is native (pacman/brew) and already on PATH.
_jl=$(configsys location julia 2>/dev/null)
if [ -n "$_jl" ]; then
    _jlbin=$(ls -d "$_jl"/julia-*/bin 2>/dev/null | sort -V | tail -n 1)
    [ -d "$_jlbin" ] && case ":$PATH:" in *":$_jlbin:"*) ;; *) PATH="$PATH:$_jlbin"; export PATH ;; esac
    unset _jlbin
fi
unset _jl
