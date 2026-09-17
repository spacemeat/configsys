# Node: npm global CLIs (user scope, --prefix ~/.local) install to ~/.local/bin.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
