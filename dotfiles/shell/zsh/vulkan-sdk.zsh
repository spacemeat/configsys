# Vulkan SDK: source its setup-env.sh from wherever configsys installed the SDK (honors your
# CONFIGSYS_SDK_DIR / scope). The tarball unpacks into a versioned subdir under the install
# location, so glob for the newest.
_vk=$(configsys location vulkan-sdk 2>/dev/null)
if [ -n "$_vk" ]; then
    _vkenv=$(ls -d "$_vk"/*/setup-env.sh 2>/dev/null | sort -V | tail -n 1)
    [ -r "$_vkenv" ] && source "$_vkenv"
fi
unset _vk _vkenv
