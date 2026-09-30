# Ruby: user-installed gems (incl. bundler) put binaries in Gem.user_dir/bin (path varies by
# distro/ruby version), so query it.
if command -v ruby >/dev/null 2>&1; then
    _gd=$(cs_cached ruby-gem-user-dir ruby ruby -e 'print Gem.user_dir')   # cached: re-runs only after a ruby upgrade
    [ -n "$_gd" ] && [ -d "$_gd/bin" ] && export PATH="$PATH:$_gd/bin"
    unset _gd
fi
