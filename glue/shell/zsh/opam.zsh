# opam: load the OCaml switch environment so opam-installed tools (dune, etc.) are on PATH.
command -v opam >/dev/null 2>&1 && [ -d "$HOME/.opam" ] && eval "$(opam env 2>/dev/null)"
