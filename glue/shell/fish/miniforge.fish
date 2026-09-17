# Miniforge/conda: load the fish integration so `conda`/`conda activate` work (no base auto-activate).
test -f "$HOME/miniforge3/etc/fish/conf.d/conda.fish"; and source "$HOME/miniforge3/etc/fish/conf.d/conda.fish"
