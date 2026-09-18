# Dart: `dart pub global activate` executables live in ~/.pub-cache/bin.
use path
var pubcache = $E:HOME/.pub-cache
if (has-env PUB_CACHE) { set pubcache = $E:PUB_CACHE }
set-env PUB_CACHE $pubcache
if (and (path:is-dir $pubcache/bin) (not (has-value $paths $pubcache/bin))) {
  set paths = [$@paths $pubcache/bin]
}
