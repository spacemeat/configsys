IMAGE_PATH="setup-env.sh"
USER_PATH=$(ls -d $HOME/vulkan/*/ | sort -V | tail -n 1)
SYSTEM_PATH=$(ls -d /opt/vulkan/*/ | sort -V | tail -n 1)
for _up in "${USER_PATH}${IMAGE_PATH}" "${SYSTEM_PATH}${IMAGE_PATH}"; do
    [ -x "$_up" ] && {
        source "$_up"
        break
    }
done
unset _up
