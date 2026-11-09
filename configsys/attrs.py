'''attrs.py — the component `attrs:` vocabulary (docs/component-attrs.md): the cross-cutting kind tags,
grouped by AXIS. One table for everyone who reads it — the TUI Profiles faceted filter
(tui/modals.py), and `check`'s `unknown-attr` lint (routecheck.validate), so an off-vocabulary tag is
flagged instead of silently never matching a filter.'''

# (axis, [tag, …]) — canonical case as authored; matching is case-insensitive (ATTR_AXIS_OF keys).
ATTR_AXES = [
    ('interface', ['CLI', 'TUI', 'GUI', 'daemon', 'web', 'headless']),
    ('role',      ['lib', 'SDK', 'app', 'toolchain', 'runtime', 'driver', 'font',
                   'theme', 'plugin', 'game', 'service', 'group', 'dotfiles', 'glue']),
    ('license',   ['FOSS', 'FOSSish', 'proprietary', 'source-available', 'freeware',
                   'GNU', 'copyleft', 'permissive']),
    ('data',      ['tele', 'tele-optin', 'account', 'cloud', 'online', 'ads', 'paid', 'freemium']),
    ('pedigree',  ['electron', 'patent', 'legacy', 'beta']),
]

# lowercased tag -> its axis
ATTR_AXIS_OF = {t.lower(): axis for axis, tags in ATTR_AXES for t in tags}


def unknown_attrs(attrs):
    '''The tags of `attrs` outside the vocabulary (case-insensitive), in order, deduplicated.'''
    out = []
    for a in attrs or ():
        a = str(a)
        if a.lower() not in ATTR_AXIS_OF and a not in out:
            out.append(a)
    return out
