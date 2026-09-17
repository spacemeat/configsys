# Composer: `composer global require` installs binaries to the global vendor bin.
_cv="${COMPOSER_HOME:-$HOME/.config/composer}/vendor/bin"
[ -d "$_cv" ] && export PATH="$PATH:$_cv"
[ -d "$HOME/.composer/vendor/bin" ] && export PATH="$PATH:$HOME/.composer/vendor/bin"
unset _cv
