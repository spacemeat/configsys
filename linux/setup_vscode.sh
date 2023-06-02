# vscode stuff
vscode_deb="~/Downloads/vscode-linux-deb-x64-stable.deb"
wget -O $vscode_deb https://code.visualstudio.com/sha/download?os=linux-deb-x64&build=stable

if hasFiles $vscode_deb ; then
        shopt -s nullglob
        files=($vscode_deb)
        shopt -u nullglob
        n=${#files[*]}

        echo "Installing vscode from ${files[n-1]}..."

        sudo apt install ${files[n-1]}

        pushd ~/src
        git clone git@github.com:spacemeat/autumnal-theme.git
        pushd autumnal-theme
        nvm install 14.0
        nvm use 14.0
        npm install -g @vscode/vsce
        npm install
        vsce package
        code --install-extension ./autumnal-theme-0.0.1.vsix
        popd ; popd
        nvm use node
fi

