# apod: splat NASA's Astronomy Picture of the Day (termapod) on interactive shell startup. Guarded on
# an interactive shell so it never dumps an image into a script / scp / non-interactive ssh command.
# No-op until apod (termapod) is installed.
case $- in
    *i*) command -v termapod >/dev/null 2>&1 && termapod ;;
esac
