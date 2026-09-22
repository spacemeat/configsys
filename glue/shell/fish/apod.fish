# apod: splat NASA's Astronomy Picture of the Day (termapod) on interactive shell startup. Interactive-
# guarded so it never dumps an image into a non-interactive shell. No-op until termapod is installed.
if status is-interactive; and command -v termapod >/dev/null 2>&1
    termapod
end
