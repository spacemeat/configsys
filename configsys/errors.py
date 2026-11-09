'''errors.py — configsys exception types.

Kept deliberately small; the app surfaces these to the user as friendly,
actionable messages ("no surprises") rather than tracebacks.
'''


class ConfigsysError(Exception):
    '''Base for all configsys errors.'''


class ConfigError(ConfigsysError):
    '''A problem in the user's config/routes data (a bad file, a malformed definition). An
    unroutable component name is a resolve.ResolveError.'''

