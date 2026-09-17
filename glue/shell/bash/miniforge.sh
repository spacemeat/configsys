# Miniforge/conda: load the shell hook so `conda`/`conda activate` work (no base auto-activate).
[ -f "$HOME/miniforge3/etc/profile.d/conda.sh" ] && . "$HOME/miniforge3/etc/profile.d/conda.sh"
