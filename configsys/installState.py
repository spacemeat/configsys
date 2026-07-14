'''installState.py defines the InstallState class which manages what is currently on system.'''

from humon import Trove
from pathlib import Path

class InstallState:
    def __init__(self, configPath:Path, configLibPath:Path):
        self.configPath = configPath
        self.configrove = Trove.fromFile(self.configPath)
        self.configLibPath = configLibPath
        self.configLibrove = Trove.fromFile(self.configLibPath)

    def inspect(self):
        ''' Traverse the trove for all components and get their install state. '''


