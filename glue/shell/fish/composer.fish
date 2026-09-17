# Composer: `composer global require` installs binaries to the global vendor bin.
set -l cv "$HOME/.config/composer/vendor/bin"
test -n "$COMPOSER_HOME"; and set cv "$COMPOSER_HOME/vendor/bin"
test -d "$cv"; and fish_add_path -ga "$cv"
test -d "$HOME/.composer/vendor/bin"; and fish_add_path -ga "$HOME/.composer/vendor/bin"
