'''clang.py — the \\clang family: versioned Clang/LLVM via apt.llvm.org.

Thin subclass of AltFamily. Unlike gcc's single PPA, clang versions come from the
LLVM apt repo, which is per-version and codename-specific — so the family carries the
LLVM repo as a default (key + a $CODENAME/$VERSION deb line, codename resolved in
shell). clang++ is a binary of the clang package (not a separate package), so it's
registered as an update-alternatives slave but not installed separately.

Routes need only the version (`clang-18: {}`); switch with
`update-alternatives --config clang`.
'''

from ._alt import AltFamily


class Clang(AltFamily):
    name = 'clang'
    default_slaves = ('clang++',)
    slaves_are_packages = False   # clang++ ships inside the clang-N package
    default_source = {
        'key': 'https://apt.llvm.org/llvm-snapshot.gpg.key',
        'deb': 'http://apt.llvm.org/$CODENAME/ llvm-toolchain-$CODENAME-$VERSION main',
    }
