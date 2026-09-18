# Vulkan SDK: import setup-env.sh's env (VULKAN_SDK, PATH, LD_LIBRARY_PATH, VK_LAYER_PATH, …) via bass,
# from wherever configsys installed the SDK (newest versioned subdir). No-op without bass/the SDK.
set -l loc (configsys location vulkan-sdk 2>/dev/null)
if type -q bass; and test -n "$loc"
    set -l envf (ls -d $loc/*/setup-env.sh 2>/dev/null | sort -V | tail -1)
    test -n "$envf"; and bass source "$envf"
end
