from .componentObj import ComponentObj
from .utilities import shellCmd

class Apt(ComponentObj):
    def __init__(self):
        pass

    def getVersion(self):
        cp = shellCmd(f'dpkg-query -W -f=\'${{Version}}\\n\' {self.name}'):
        if cp.returncode == 0:
            return str(cp.stdout).strip()
        return None

    def install(self):
        shellCmd(f'apt-get install {self.name}')

    def uninstall(self):
        shellCmd(f'apt-get remove {self.name}')

    def upgrade(self):
        shellCmd(f'apt-get install --only-upgrade {self.name}')

    def setVersion(self):
        shellCmd(f'apt-get install --allow-downgrades {self.name}={self.version}')

    def lockVersion(self):
        shellCmd(f'apt-mark hold {self.name}')
