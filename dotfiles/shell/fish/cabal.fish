# cabal: put cabal-installed executables (hlint, etc.) on PATH.
for d in "$HOME/.cabal/bin" "$HOME/.local/bin"
    test -d "$d"; and fish_add_path -ga "$d"
end
