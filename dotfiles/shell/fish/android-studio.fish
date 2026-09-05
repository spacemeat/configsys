# android-studio: alias `studio`/`android-studio` to the tarball launcher (bin/studio or bin/studio.sh).
set -l loc (configsys location android-studio 2>/dev/null)
if test -n "$loc"
    for c in "$loc/bin/studio" "$loc/bin/studio.sh"
        if test -x "$c"
            alias android-studio "$c"
            alias studio "$c"
            break
        end
    end
end
