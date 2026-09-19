# Vulkan SDK: source its setup-env.sh (sets VULKAN_SDK + PATH/LD_LIBRARY_PATH/VK_LAYER_PATH) from
# wherever configsys installed the SDK (a versioned subdir under the managed location; newest wins).
# No-op where the SDK isn't a managed install.
let vk = (cs-loc vulkan-sdk)
if ($vk != "") {
  cs-bash-env ('_e=$(ls -d "' + $vk + '"/*/setup-env.sh 2>/dev/null | sort -V | tail -1); [ -r "$_e" ] && source "$_e"')
}
