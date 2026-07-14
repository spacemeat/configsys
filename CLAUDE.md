# configsys

Configsys is a single tool for setting up a new operating system installation and account from a config and TUI application. The notion is that not only are dotfiles able to be synchronized across systems (via a remote git repository) but that, whether the system is linux, unix, or macos, we are able to, from a TUI tool and bash, select a user profile and quickly sync os-native packages, appImages, flatpaks, SDKs, distributed binaries, or other means of software distribution. We want total control over updating, version locking, and removal of any such component, and to be able to easily modify the config and routes files to further refine the (relatively) uniform setup.

## Architecture

Every system we care about either comes with a version of python3, or that must be the first requirement of the system. Additionally, there is a python library in PyPI called humon, which we can use as well (see skill). From there, we are able to read and use routes.hu and config.hu to:
- determine, depending on the OS, the install/update mechanism for a component
- determine the installation state (whether installed, what version, is it latest, is it version-locked) of a component
- install a component to latest version
- change a component to a particular version or upgrade to its latest
- lock / unlock a component version

The application should be python3, and so python3 and humon must be the first to synchronize; this can be done via bash, since we need these components for the rest of the app. The app should be an interactive TUI, and slick looking on a 24-bit RGB terminal. It should be menu-driven, with single-key actions and menu navigation via VIM-like controls.

On start, a file called configsys.hu should be present in ~. If it is not, one must be generated from a template config from the repo. If it contains a top-level node called 'configs' with a single value or list, those values are the profiles that concern this installation. For each profile that matches another top-level node (example: dev) the app will search the system to find all the installed components already on the system and evaluate their versions. From that known state, an interactive menu will let user:

- view the install state of each component
- interactively mark installed components for an operation (upgrade, remove, etc)
- quickly mark all components for an operation (select all in profile)

In the repo, routes.hu maps the OS to the installation medium (apt, dnf, pacman, AUR, appImage, flatpak, etc). OSs cascade; where pop_os! uses ubuntu, and inherits all of ubuntu's routes; ubuntu inherits debian's routes, etc. Inheritance is marked as a node beginning with !using. Blocks whose name starts with '\' specify families; a node referencing a family (install medium) specifies "<family>\<component>" (ex: apt\xclip). This directs the app to use the family description for this component. If a node does not contain a family spec, then it is found by checking the cascaded OS block first. If a node called * is in the block, the value will specify a node by replacing * in the value. (debian's block specifies '*: apt\*'. Debian uses apt for native packages.) A node in an OS profile may also be a list, in which case each entry is looked up independently by name and considered part of the component. A node in a family profile may also be a dict, which allows variables to be set. A system for specifying the appropriate dotfiles for each component should also be configured; whatever is needed by, say, neovim, using the appropriate env variables to specify paths which are sync'd from the repo's dotfiles directory.

Family profiles are defined in code according to their major operations: getVersion, install, uninstall, upgrade, setVersion, lockVersion, unlockVersion. apt has various commands for doing these; as does flatpak, etc. More families can be added as needed.

More details will be fleshed out with /grill-me and examining the code already in place.

The bash bootstrap must be minimal; ensure an adequate python3 version is installed globally (3.10 is a fine choice), and a virtual environment exists (.venv) in the repo directory, and humon is installed. From there, the rest of the app should be in python.

## Some considerations

User should have control of what goes into profiles and which profiles they wish to use. Components that overlap in profiles shoudln't be doubled up; if there are family conflicts between components, user should be notified to fix the conflict before other things can proceed. In general, take a posture of 'no surprises'; user should know what's installed, what's going to be when they do an operation, and what's not. However, user does not need all details about package dependencies in apt, for example.

