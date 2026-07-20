UNIT_PATH="arduino-ide.appimage"
for _up in "$HOME/apps/$UNIT_PATH" "/opt/apps/$UNIT_PATH"; do
    [ -x "$_up" ] && {
        alias arduino="$_up"
        break
    }
done
unset _up
