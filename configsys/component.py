''' component.py defines the base component class. Other component types must support these things.'''


class Component:
    def __init__(self, componentObj):
        self.componentObj = componentObj

    def getVersion(self):
        raise NotImplementedError('getVersion')

    def install(self):
        raise NotImplementedError('install')

    def uninstall(self):
        raise NotImplementedError('uninstall')

    def upgrade(self):
        raise NotImplementedError('upgrade')

    def setVersion(self):
        raise NotImplementedError('setVersion')

