# fzf: resolve the binary (native on PATH, else the managed tarball) as `fzf`, and add nushell-NATIVE
# keybindings. fzf generates bash/zsh/fish integration, but has NO nushell target — and its bindings
# are readline/zle widgets (line-editor state), not env, so they can't be imported (cs-bash-env) or
# eval'd (#!cs-eval). So they're authored here as Reedline keybindings that run fzf and edit the line:
#   Ctrl-R  fuzzy history search        Ctrl-T  insert selected file path(s)        Alt-C  cd into a dir
# The Ctrl-T / Alt-C sources honour $FZF_CTRL_T_COMMAND / $FZF_ALT_C_COMMAND, else `find` (minus .git).
$env.__cs_fzf = (do { let loc = (cs-loc fzf); if (($loc != "") and ($"($loc)/fzf" | path exists)) { $"($loc)/fzf" } else { "" } })
def --wrapped fzf [...rest] { if ($env.__cs_fzf? | is-not-empty) { ^$env.__cs_fzf ...$rest } else { ^fzf ...$rest } }

def cs-fzf-files [] {
  if ($env.FZF_CTRL_T_COMMAND? | is-not-empty) { ^bash -c $env.FZF_CTRL_T_COMMAND } else { ^find . -mindepth 1 -type f -not -path "*/.git/*" e> /dev/null }
}
def cs-fzf-dirs [] {
  if ($env.FZF_ALT_C_COMMAND? | is-not-empty) { ^bash -c $env.FZF_ALT_C_COMMAND } else { ^find . -mindepth 1 -type d -not -path "*/.git/*" e> /dev/null }
}

# Append (never overwrite) — keep the user's other keybindings. Our block runs at the end of config.nu,
# after any $env.config the user set, so this appends onto it.
$env.config.keybindings = (($env.config.keybindings? | default []) | append [
  { name: fzf_history  modifier: control  keycode: char_r  mode: [emacs vi_normal vi_insert]
    event: { send: executehostcommand
      cmd: 'let sel = (history | get command | reverse | uniq | str join (char newline) | fzf --scheme=history --height "40%" --reverse --query (commandline) | str trim); if ($sel | is-not-empty) { commandline edit --replace $sel }' } }
  { name: fzf_file  modifier: control  keycode: char_t  mode: [emacs vi_normal vi_insert]
    event: { send: executehostcommand
      cmd: 'let f = (cs-fzf-files | fzf --multi --height "40%" --reverse | lines | where {|x| $x != "" } | str join " "); if ($f | is-not-empty) { commandline edit --insert $f }' } }
  { name: fzf_cd  modifier: alt  keycode: char_c  mode: [emacs vi_normal vi_insert]
    event: { send: executehostcommand
      cmd: 'let d = (cs-fzf-dirs | fzf --height "40%" --reverse | str trim); if ($d | is-not-empty) { cd $d }' } }
])
