'''errors.py — configsys exception types.

Kept deliberately small; the app surfaces these to the user as friendly,
actionable messages ("no surprises") rather than tracebacks.
'''


class ConfigsysError(Exception):
    '''Base for all configsys errors.'''


class ConfigError(ConfigsysError):
    '''A problem in the user's config/routes data (bad file, unresolvable name).'''


class ResolveError(ConfigError):
    '''A component name could not be routed on the active OS.'''

    def __init__(self, name, os_block, detail=None):
        self.name = name
        self.os_block = os_block
        self.detail = detail
        msg = f'no route for "{name}" on {os_block}'
        if detail:
            msg += f' ({detail})'
        super().__init__(msg)
