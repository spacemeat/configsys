# GNUstep: source the build environment (GNUSTEP_MAKEFILES + the GNUSTEP_* path vars) so gnustep-make
# and GNUstep apps build/run. Tries the usual install locations; no-op if none is present.
cs-bash-env 'for _gs in /usr/share/GNUstep/Makefiles/GNUstep.sh /usr/GNUstep/System/Library/Makefiles/GNUstep.sh /usr/local/share/GNUstep/Makefiles/GNUstep.sh; do [ -r "$_gs" ] && { . "$_gs"; break; }; done'
