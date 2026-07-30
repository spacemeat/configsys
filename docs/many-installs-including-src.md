# Install options

> **Status: SUPERSEDED (shipped).** This is the early musing that seeded the multi-install and
> build-from-source work. Its ideas were scoped in `install-methods-plan.md` and are now shipped
> (multi-method selection + the declarative `source` driver). Kept only as the original framing.

Configsys is, by default, opinionated about what install method a component should use. Yes, there are options, but they're gated by drivers, and must be pinned for users to have an opinion. This is mostly fine, and mostly works well. It *feels* like the default options are too rigid; somethings can install natively, but may have flatpak versions as well, and we aren't referencing them. Some OSs don't work well with multiple install sources for an app. Sometimes (usually) partiuclar drivers have different latest-versions, and other tradeoffs.

## Install From Source as a First Class Driver

Currently there are several projects which can optionally install via building from source (Blender; Kicad). They're pretty specific to the applications, as any build-from-source driver must be. However, there are more projects which *can* be built from source, and users may want the option for any or all of these--think in the spirit of Gentoo--and we've kind of been giving these a back seat. Now, most users *won't* care about building from source, unless their OS prevents an easy native installation, say. But that's no reason to artificially gate the experience. I'd like to explore making from-source installs a first-class driver.

### Applies to apps, sdks, services... whatever user wants

Anything we manage in configsys should have source available, and build methods to do it. But there are a lot of caveats to building projects: specific language environments, EULA requirements for some components, pre- and post-install scripts that must be run, ultimate build targets (scripts or binaries) that must be run from particular locations or emplaced on $PATH, specific uninstall steps. The source itself will be versioned, but may have its version referenced in particular ways in-source. And all this may change over time. Plugins already support shipping source that can perform these customized operations.

### The struggle is real

Each build having its own bespoke methods for checking, installing, scope, uninstalling, specific scripts, specific dependencies, and differences on a per-OS basis seems to encourage a custom driver for each component. Which indicates that our approach so far--a plugin for really complex builds--is likely correct. But a number of components may simply build with a make/CMake option and an alias script in bash.d. Many of these could be given simple scripts in the base configsys project without too much fanfare--but is it worth doing?

## On native, flatpak, snap, install-from-source, install-from-published-deb... and on and on

I *think* what I'm looking for is for each component to expose as many install methods for each OS as it can. Chrome on native, flatpak, snap, etc. As long as there are methods I can choose from on my OS, I should be able to pin any of them. I think that means fleshing out each component's possible methods, gating their requirements per-OS (and removing unnecessary opinionated where: clauses that exist for historic reasons only), and giving users a chance to *see* and *choose* which methods they want for a component, exposing version information, maybe even allowing for side-by-side installations where it's possible. This all may be unknowable information up front, especially side-by-side feasibility, and particular build setups.

### Install method via pins, and how they get stored

Users selecting install methods via pinning is compelling, since it is a working system. However, this is the first change that asks the TUI to update any files beyond the lock manifest. The pins would be, I fell, important to be part of user's personal config, so that a from-source build on one machine becomes a from-source build on other machines too--no surprises. Users would be expected to really manage their own configs. However, since at TUI time the pins can be selected/changed, users would still have options--overrides would live in their ~/.config/configsys directory, like normal. I'd explore maybe a separate pins file for install method selection state. Alternately, the pins *could* live in their local configsys.hu, but we'd want to explore having override properties in a component, rather than full overrides. Maybe with a configsys command to promote the overrides to the primary plugin.

