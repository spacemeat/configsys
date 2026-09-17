# pipx: installed apps (jupyterlab, etc.) land on ~/.local/bin.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
