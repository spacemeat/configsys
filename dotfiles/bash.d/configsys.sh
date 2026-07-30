# configsys — standard install layout ("config for configsys"). configsys uses these dirs to
# decide WHERE it puts things; exporting them here keeps your shell and configsys in agreement.
# Override any value in your own shell config BEFORE this file runs to relocate a whole class of
# installs; configsys falls back to these same defaults when a variable is unset.
#
# An install location is:  <scope base>/<category>/<name>
#   category (set below):  apps/ for self-contained apps, sdks/ for SDKs+libs, src/ for builds
#   scope base (advanced): your home for user-scope, /opt for system-scope
: "${CONFIGSYS_APP_DIR:=apps}"          # tarball/appImage apps -> ~/apps/<name>
: "${CONFIGSYS_SDK_DIR:=sdks}"          # SDKs and libraries    -> ~/sdks/<name>
: "${CONFIGSYS_SRC_DIR:=src}"           # source-build trees    -> ~/src/<name>
export CONFIGSYS_APP_DIR CONFIGSYS_SDK_DIR CONFIGSYS_SRC_DIR

# Scope bases (advanced) — where user/system installs root. Defaults: your home and /opt.
# Uncomment to relocate everything (e.g. onto another volume):
#   export CONFIGSYS_USERSCOPE_DIR="$HOME"  CONFIGSYS_SYSTEMSCOPE_DIR=/opt

alias cf="~/src/configsys/configsys.sh"
