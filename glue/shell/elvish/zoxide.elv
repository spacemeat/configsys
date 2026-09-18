# zoxide — a smarter cd (`z`/`zi`). Needs a MODERN zoxide with elvish support; the old Ubuntu/Pop
# 0.4.x has none, so `zoxide init elvish` errors. ?() swallows that (a bare error would abort the
# rest of the gestalt rc block). zoxide's init uses edit:add-var, so the commands persist.
if (has-external zoxide) {
  nop ?(eval (zoxide init elvish 2>/dev/null | slurp))
}
