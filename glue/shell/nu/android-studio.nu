# android-studio: alias studio/android-studio to the tarball launcher.
$env.__cs_android_studio = (do { let loc = (cs-loc android-studio); if ($loc == "") { "" } else { ([$"($loc)/bin/studio"] ++ [$"($loc)/bin/studio.sh"] | where {|p| ($p | path exists)} | get 0? | default "") } })
def --wrapped studio [...rest] { if ($env.__cs_android_studio? | is-not-empty) { ^$env.__cs_android_studio ...$rest } else { ^studio ...$rest } }
def --wrapped android-studio [...rest] { if ($env.__cs_android_studio? | is-not-empty) { ^$env.__cs_android_studio ...$rest } else { ^android-studio ...$rest } }
