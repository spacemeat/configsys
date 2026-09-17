# GNUstep: source the build environment (sets GNUSTEP_MAKEFILES + the GNUSTEP_* path vars) so
# gnustep-make and GNUstep apps build/run. Guarded — only sources if GNUstep is installed.
for _gs in /usr/share/GNUstep/Makefiles/GNUstep.sh \
           /usr/GNUstep/System/Library/Makefiles/GNUstep.sh \
           /usr/local/share/GNUstep/Makefiles/GNUstep.sh; do
    [ -r "$_gs" ] && { . "$_gs"; break; }
done
unset _gs
