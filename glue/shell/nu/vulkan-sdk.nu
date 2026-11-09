# Vulkan SDK: source its setup-env.sh (sets VULKAN_SDK + PATH/LD_LIBRARY_PATH/VK_LAYER_PATH) from
# wherever configsys installed the SDK (a versioned subdir under the managed location; newest wins).
# No-op where the SDK isn't a managed install.
# The location is single-quoted for bash (a `'` inside it closed and re-opened), so no character in it
# is ever bash syntax; it stays in the command text, so the memo key still changes with it.
let vk = (cs-loc vulkan-sdk)
if ($vk != "") {
  let q = ("'" + ($vk | str replace --all "'" "'\\''") + "'")
  cs-bash-env ('_e=$(ls -d ' + $q + '/*/setup-env.sh 2>/dev/null | sort -V | tail -1); [ -r "$_e" ] && source "$_e"')
}
