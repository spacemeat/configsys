# GNUstep: import the GNUstep.sh build env (GNUSTEP_MAKEFILES + the GNUSTEP_* path vars) via bass.
# No-op without bass / where GNUstep isn't installed.
if type -q bass
    for f in /usr/share/GNUstep/Makefiles/GNUstep.sh /usr/GNUstep/System/Library/Makefiles/GNUstep.sh /usr/local/share/GNUstep/Makefiles/GNUstep.sh
        if test -r "$f"
            bass source "$f"
            break
        end
    end
end
