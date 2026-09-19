# atuin — shell history: sync, search, and stats. nushell has no runtime source/eval, so the glue
# driver captures `atuin init nu` at (de)activation and inlines it (the cs-eval generator directive).
# No-op (nothing inlined) where atuin isn't installed.
#!cs-eval atuin init nu
