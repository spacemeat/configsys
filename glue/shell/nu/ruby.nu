# Ruby: user gems install to Gem.user_dir/bin (path varies) — query it. No-op if ruby absent.
if (which --all ruby | where type == "external" | is-not-empty) {
  let gd = (do --ignore-errors { ^ruby -e 'print Gem.user_dir' | complete })
  if (($gd != null) and ($gd.exit_code == 0)) { cs-append $"(($gd.stdout | str trim))/bin" }
}
