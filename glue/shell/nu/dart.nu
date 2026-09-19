# Dart: `dart pub global activate` executables live in $PUB_CACHE/bin (~/.pub-cache).
$env.PUB_CACHE = ($env.PUB_CACHE? | default $"($env.HOME)/.pub-cache")
cs-append $"($env.PUB_CACHE)/bin"
