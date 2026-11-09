'''gcc.py — the gcc driver: versioned GCC via the toolchain PPA + update-alternatives.

Thin subclass of AltDriver. Routes provide the packages and the slaves (g++), which
for gcc are their own apt packages (gcc-13, g++-13), plus — only on an Ubuntu release
whose own repos lack that gcc — `ppa: ubuntu-toolchain-r/test`. Switch the active
version with `update-alternatives --config gcc`.
'''

from ._alt import AltDriver


class Gcc(AltDriver):
    name = 'gcc'
