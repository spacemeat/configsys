# clang: `clangv` opens the update-alternatives picker for the default clang.
def clangv [] { ^sudo update-alternatives --config clang }
