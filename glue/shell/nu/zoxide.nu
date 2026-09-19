# zoxide — a smarter cd (`z`/`zi`). nushell has no runtime source/eval, so the glue driver captures
# `zoxide init nushell` at (de)activation and inlines it (the cs-eval generator directive below).
# Needs a MODERN zoxide with nushell support; the old apt/Pop 0.4.x has none, so the directive exits
# non-zero and nothing is inlined (self-guard) — install a newer zoxide (cargo) to light it up.
#!cs-eval zoxide init nushell
