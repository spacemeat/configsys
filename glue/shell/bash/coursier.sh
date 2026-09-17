# coursier: add the coursier apps bin (populated by `cs install`) to PATH. `cs` itself is on
# PATH via sdkman; this exposes the applications coursier installs.
_csbin="${COURSIER_BIN_DIR:-$HOME/.local/share/coursier/bin}"
[ -d "$_csbin" ] && case ":$PATH:" in *":$_csbin:"*) ;; *) PATH="$PATH:$_csbin"; export PATH ;; esac
unset _csbin
