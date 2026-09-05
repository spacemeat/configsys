# Dart: `dart pub global activate` executables live in ~/.pub-cache/bin.
set -q PUB_CACHE; or set -gx PUB_CACHE "$HOME/.pub-cache"
test -d "$PUB_CACHE/bin"; and fish_add_path -ga "$PUB_CACHE/bin"
