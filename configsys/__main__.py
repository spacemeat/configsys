import os
import sys

# configsys.sh cds into the repo so `-m configsys` finds the package; hand the process back to the
# directory you ran it from, so a relative path on the command line means YOUR directory (B12)
_cwd = os.environ.pop('CONFIGSYS_INVOKED_CWD', None)
if _cwd:
    try:
        os.chdir(_cwd)
    except OSError:
        pass

from .app import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
