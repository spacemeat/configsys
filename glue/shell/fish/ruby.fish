# Ruby: user-installed gems put binaries in Gem.user_dir/bin (path varies by distro/ruby), so query it.
if command -v ruby >/dev/null 2>&1
    set -l gd (cs_cached ruby-gem-user-dir ruby ruby -e 'print Gem.user_dir')   # cached: re-runs only after a ruby upgrade
    test -n "$gd"; and test -d "$gd/bin"; and fish_add_path -ga "$gd/bin"
end
