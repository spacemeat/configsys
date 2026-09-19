# Miniforge/conda: load the conda shell hook (CONDA_EXE + condabin on PATH) so the `conda` binary
# works for basic ops. `conda activate` needs the shell FUNCTION, which doesn't cross to nu — for env
# activation use nushell's own conda integration. No-op if miniforge isn't installed.
cs-bash-env '[ -f "$HOME/miniforge3/etc/profile.d/conda.sh" ] && . "$HOME/miniforge3/etc/profile.d/conda.sh"'
