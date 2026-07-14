'componentObj.py defines the component object as flattened from the config hierarchy.'

from humon import Trove

class ComponentObj:
    def __init__(self, trove:Trove, componentName):
        self.name = componentName

    def findBestFit():
        ''' Traverses the trove until the best (most precise fitting) named item is found.
        Dependencies are similarly searched, building up an object until everything is
        resolved.'''
        pass

