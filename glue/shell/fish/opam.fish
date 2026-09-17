# opam: load the OCaml switch environment so opam-installed tools (dune, etc.) are on PATH.
if command -v opam >/dev/null 2>&1; and test -d "$HOME/.opam"
    opam env --shell=fish 2>/dev/null | source
end
