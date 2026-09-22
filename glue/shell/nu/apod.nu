# apod: splat NASA's Astronomy Picture of the Day (termapod) on shell startup (config.nu runs for
# interactive sessions only, so no extra guard needed). No-op until termapod is installed.
if (which termapod | where type == "external" | is-not-empty) { termapod }
