# Dart: `dart pub global activate` executables live in ~/.pub-cache/bin.
export PUB_CACHE="${PUB_CACHE:-$HOME/.pub-cache}"
[ -d "$PUB_CACHE/bin" ] && export PATH="$PATH:$PUB_CACHE/bin"
