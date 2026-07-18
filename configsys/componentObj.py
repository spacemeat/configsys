'''componentObj.py — ResolvedComponent: one concrete installable unit.

A profile names OS-level components (e.g. "neovim", "btop"); routes.hu resolves
each to one or more concrete *units*, each bound to a driver (apt, flatpak, ...).
The unit key `driver\\comp` is the dedup identity: two profile entries that resolve
to the same unit collapse to one, so nothing is installed twice.
'''

from dataclasses import dataclass, field


@dataclass
class ResolvedComponent:
    key: str                                    # "driver\\comp" — dedup identity
    driver: str                                 # e.g. "apt", "flatpak", "appImage"
    comp: str                                   # component name within the driver
    fields: dict = field(default_factory=dict)  # driver-node fields ($vars substituted)
    vars: dict = field(default_factory=dict)    # variables in scope (fonts, etc.)
    requested_as: set = field(default_factory=set)  # OS-level names that pulled it in
    deps: set = field(default_factory=set)      # unit keys this unit requires first
    source: str = ''                            # routes.hu node address (diagnostics)

    @property
    def name(self):
        '''The package/app identifier the driver operates on.'''
        return self.fields.get('name', self.comp)

    @property
    def display(self):
        reqs = ', '.join(sorted(self.requested_as))
        return f'{self.key} (for {reqs})' if reqs else self.key
