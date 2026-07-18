'''gcc.py — the gcc driver: versioned GCC via the toolchain PPA + update-alternatives.

Thin subclass of AltDriver. Routes provide `ppa` (ubuntu-toolchain-r/test) and the
slaves (g++), which for gcc are their own apt packages (gcc-13, g++-13). Switch the
active version with `update-alternatives --config gcc`.
'''

from ._alt import AltDriver


class Gcc(AltDriver):
    name = 'gcc'
