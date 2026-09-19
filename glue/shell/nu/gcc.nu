# gcc: `gccv` opens the update-alternatives picker for the default gcc.
def gccv [] { ^sudo update-alternatives --config gcc }
