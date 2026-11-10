#!/usr/bin/env bash
# repos.sh — status / push / tag across the whole configsys repo fleet.
#
# The fleet is this repo (configsys, the base) plus its `configsys-*` siblings under the same
# parent dir (the plugin repos). With no argument it just REPORTS; the mutating modes are opt-in.
#
# Usage:
#   tools/repos.sh [status]     report each repo: HEAD, ahead/behind origin, latest vX.Y.Z tag,
#                               and any staged/unstaged/untracked files                (read-only)
#   tools/repos.sh push [--yes] push each repo's current branch to origin (only repos ahead of it)
#   tools/repos.sh tag | tag-patch | tag-minor | tag-major [--yes]
#                               bump the latest vX.Y.Z tag (patch / minor+reset / major+reset), then
#                               push the BRANCH and the new tag together (so the tag lands on a commit
#                               that's actually on origin's branch, not one reachable only via the
#                               tag). Skips a repo with no commits since its latest tag, any repo with
#                               no tag yet (see tag-init; configsys itself stays tagless until 1.0),
#                               and any repo with uncommitted or untracked files. Keeps the tag's
#                               style: 1.2.3 -> 1.2.4, v1.2.3 -> v1.2.4.
#   tools/repos.sh tag-init <repo> [vX.Y.Z] [--yes]
#                               give a configsys-* repo with no tags its FIRST tag (default v0.1.0)
#                               on HEAD and push it with the branch; later `tag` runs bump it.
#
# Every mode prints the status report first. push / tag / tag-init then print the PLAN — each repo
# and exactly what will happen to it, or why it's skipped — and ask once (`--yes` skips the question).
set -uo pipefail

cmd='' yes=0 posargs=()
for arg in "$@"; do
  case "$arg" in
    -y|--yes) yes=1 ;;
    *) if [ -z "$cmd" ]; then cmd=$arg; else posargs+=("$arg"); fi ;;
  esac
done
cmd=${cmd:-status}
case "$cmd" in
  status|'')            action=report ;;
  push)                 action=push ;;
  tag|tag-patch)        action=tag; kind=patch ;;
  tag-minor)            action=tag; kind=minor ;;
  tag-major)            action=tag; kind=major ;;
  tag-init)             action=init ;;
  -h|--help|help)       awk 'NR>1 && /^#/{sub(/^# ?/,""); print; next} NR>1{exit}' "$0"; exit 0 ;;
  *) echo "repos.sh: unknown command '$cmd' (try: status | push | tag[-patch|-minor|-major] | tag-init <repo>)" >&2; exit 2 ;;
esac
if [ "$action" = init ]; then
  [ ${#posargs[@]} -ge 1 ] && [ ${#posargs[@]} -le 2 ] || { echo "repos.sh: usage: tag-init <repo> [vX.Y.Z] [--yes]" >&2; exit 2; }
  init_name=${posargs[0]} init_tag=${posargs[1]:-v0.1.0}
  [[ $init_tag =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "repos.sh: '$init_tag' isn't a vX.Y.Z tag" >&2; exit 2; }
elif [ ${#posargs[@]} -gt 0 ]; then
  echo "repos.sh: unexpected argument '${posargs[0]}'" >&2; exit 2
fi

# -- colors (off when not a tty or NO_COLOR set) -------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\e[1m'; DIM=$'\e[2m'; RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'; CYA=$'\e[36m'; RST=$'\e[0m'
else
  BOLD=''; DIM=''; RED=''; GRN=''; YEL=''; CYA=''; RST=''
fi

# -- discover the fleet: base repo first, then configsys-* siblings ------------------------------
SELF=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)   # this repo (base)
PARENT=$(dirname "$SELF")
repos=()
[ -d "$SELF/.git" ] && repos+=("$SELF")
for d in "$PARENT"/configsys-*; do
  [ -d "$d/.git" ] && repos+=("$d")
done
if [ ${#repos[@]} -eq 0 ]; then echo "repos.sh: no git repos found" >&2; exit 1; fi

g() { git -C "$1" "${@:2}"; }   # g <repo> <git args...>

# highest vX.Y.Z tag in a repo (empty if none)
latest_tag() {
  g "$1" tag --list --sort=-v:refname 2>/dev/null \
    | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' | head -n1
}

# bump <[v]X.Y.Z> <patch|minor|major> -> the new tag, in the same style (fails on an unparseable tag)
bump() {
  [[ $1 =~ ^(v?)([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || return 1
  local v=${BASH_REMATCH[1]} M=${BASH_REMATCH[2]} m=${BASH_REMATCH[3]} p=${BASH_REMATCH[4]}
  case $2 in
    patch) p=$((p + 1)) ;;
    minor) m=$((m + 1)); p=0 ;;
    major) M=$((M + 1)); m=0; p=0 ;;
  esac
  printf '%s%s.%s.%s' "$v" "$M" "$m" "$p"
}

# -- report --------------------------------------------------------------------------------------
report() {
  local repo=$1 name head tag_raw tag up ahead behind loc st tagseg
  name=$(basename "$repo")
  head=$(g "$repo" symbolic-ref --short -q HEAD) || head="detached@$(g "$repo" rev-parse --short HEAD)"
  tag_raw=$(latest_tag "$repo"); tag=${tag_raw:-'(no tags)'}

  if up=$(g "$repo" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null); then
    read -r behind ahead < <(g "$repo" rev-list --left-right --count "${up}...HEAD" 2>/dev/null)
    loc="${GRN}↑${ahead:-0}${RST} ${RED}↓${behind:-0}${RST} ${DIM}vs ${up}${RST}"
  else
    loc="${YEL}(no upstream)${RST}"
  fi

  # commits since the latest tag -> whether a `tag` push is worth it (+N in yellow when >0)
  tagseg=''
  if [ -n "$tag_raw" ]; then
    local n; n=$(g "$repo" rev-list --count "${tag_raw}..HEAD" 2>/dev/null); n=${n:-0}
    if [ "$n" -gt 0 ]; then tagseg="  ${YEL}+${n} since ${tag_raw}${RST}"
    else                    tagseg="  ${DIM}+0 since ${tag_raw}${RST}"; fi
  fi

  printf '%s%-20s%s  %sHEAD%s %-16s  %stag%s %-10s  %s%s\n' \
    "$BOLD" "$name" "$RST" "$DIM" "$RST" "$head" "$DIM" "$RST" "$tag" "$loc" "$tagseg"

  st=$(g "$repo" status --porcelain 2>/dev/null)
  if [ -n "$st" ]; then
    while IFS= read -r line; do
      local xy=${line:0:2} path=${line:3}
      local col=$YEL                             # default (mixed)
      case "$xy" in
        '??') col=$RED ;;                        # untracked
        ' '*) col=$RED ;;                        # worktree-only (unstaged)
        *' ') col=$GRN ;;                        # index-only (staged)
      esac
      printf '    %s%s%s %s\n' "$col" "$xy" "$RST" "$path"
    done <<< "$st"
  else
    printf '    %sclean%s\n' "$DIM" "$RST"
  fi
}

# -- plan: decide what each repo gets (pure: reads git, changes nothing) ---------------------------
# plan_<action> <repo> sets P_OK (1 = act on it) and P_DESC (what will happen, or "skip — why").

plan_push() {
  local repo=$1 br up a
  P_OK=0
  g "$repo" remote get-url origin >/dev/null 2>&1 || { P_DESC='skip — no origin'; return; }
  br=$(g "$repo" symbolic-ref --short -q HEAD) || { P_DESC='skip — detached HEAD'; return; }
  if up=$(g "$repo" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null); then
    a=$(g "$repo" rev-list --count "${up}..HEAD" 2>/dev/null); a=${a:-0}
    [ "$a" -eq 0 ] && { P_DESC="skip — up to date with $up"; return; }
    P_DESC="$br -> origin ($a commit$([ "$a" -eq 1 ] || echo s))"
  else
    P_DESC="$br -> origin (no upstream yet)"
  fi
  P_OK=1
}

_clean_or_skip() {   # a tag names a commit, not your worktree: tagging over uncommitted work
  if [ -n "$(g "$1" status --porcelain 2>/dev/null)" ]; then   # releases something other than what you see
    P_DESC='skip — uncommitted or untracked files (commit or stash them first)'; return 1
  fi
}

# Your primary plugin follows its branch and is never version-tagged (docs/plugins.md §8): name it
# from the top config's `primary: true` entry (a line-level read — `configsys plugin bless` writes it
# on one line).
TOP_CONFIG=${CONFIGSYS_CONFIG:-${CONFIGSYS_STATE_DIR:-${XDG_CONFIG_HOME:-${HOME:-/nonexistent}/.config}/configsys}/configsys.hu}
is_primary() {
  local name; name=$(basename "$1")
  [ -r "$TOP_CONFIG" ] && grep -Eq "[/:]${name}(\.git)?[\"' ].*primary: *(true|yes|on|1)" "$TOP_CONFIG"
}

plan_tag() {
  local repo=$1 tag n
  P_OK=0 P_NEW=''
  tag=$(latest_tag "$repo")
  if [ -z "$tag" ]; then
    if [ "$repo" = "$SELF" ]; then P_DESC='skip — no tags (configsys stays tagless until 1.0)'
    elif is_primary "$repo"; then P_DESC='skip — your primary plugin follows its branch, untagged'
    else P_DESC="skip — no tags yet (\`tools/repos.sh tag-init $(basename "$repo")\` gives it v0.1.0)"; fi
    return
  fi
  n=$(g "$repo" rev-list --count "${tag}..HEAD" 2>/dev/null); n=${n:-0}
  [ "$n" -eq 0 ] && { P_DESC="skip — no commits since $tag"; return; }
  _clean_or_skip "$repo" || return
  P_NEW=$(bump "$tag" "$kind") || { P_DESC="skip — unparseable tag $tag"; return; }
  if g "$repo" rev-parse -q --verify "refs/tags/$P_NEW" >/dev/null 2>&1; then
    P_DESC="skip — $P_NEW already exists"; return
  fi
  P_DESC="$tag -> $P_NEW  ($n commit$([ "$n" -eq 1 ] || echo s))"; P_OK=1
}

plan_init() {
  local repo=$1
  P_OK=0 P_NEW=$init_tag
  [ "$repo" = "$SELF" ] && { P_DESC='skip — configsys itself stays tagless until 1.0'; return; }
  is_primary "$repo" && { P_DESC='skip — your primary plugin follows its branch; it is never version-tagged'; return; }
  [ -n "$(latest_tag "$repo")" ] && { P_DESC="skip — already tagged ($(latest_tag "$repo")); use \`tag\` to bump it"; return; }
  _clean_or_skip "$repo" || return
  P_DESC="(no tags) -> $init_tag  (first tag, on HEAD)"; P_OK=1
}

# -- act ------------------------------------------------------------------------------------------
do_push() {
  local repo=$1 br
  br=$(g "$repo" symbolic-ref --short -q HEAD)
  if g "$repo" push origin "$br"; then printf '    %sok%s\n' "$GRN" "$RST"; else printf '    %sFAILED%s\n' "$RED" "$RST"; fi
}

do_tag() {   # <repo> <new tag>: tag HEAD and push the branch with it
  local repo=$1 new=$2 br
  br=$(g "$repo" symbolic-ref --short -q HEAD) || br=''
  g "$repo" tag "$new" || { printf '    %sFAILED (tag)%s\n' "$RED" "$RST"; return; }
  # Push the BRANCH together with the tag. A tags-only push transfers the tagged commit's OBJECTS
  # (so the tag isn't dangling) but does NOT advance origin's branch — leaving main BEHIND the tag,
  # with the commit reachable only via the tag. Pushing both keeps the tag on origin's mainline.
  if [ -n "$br" ]; then
    if g "$repo" push origin "$br" "refs/tags/$new"; then printf '    %sok — pushed %s + %s%s\n' "$GRN" "$br" "$new" "$RST"
    else printf '    %sFAILED (push %s + %s)%s\n' "$RED" "$br" "$new" "$RST"; fi
  else
    printf '    %snote — detached HEAD: %s would not be on any branch%s\n' "$YEL" "$new" "$RST"
    if g "$repo" push origin "refs/tags/$new"; then printf '    %sok — pushed %s%s\n' "$GRN" "$new" "$RST"
    else printf '    %sFAILED (push %s)%s\n' "$RED" "$new" "$RST"; fi
  fi
}

# -- run -----------------------------------------------------------------------------------------
for repo in "${repos[@]}"; do report "$repo"; done
[ "$action" = report ] && exit 0

targets=("${repos[@]}")
if [ "$action" = init ]; then
  targets=()
  for repo in "${repos[@]}"; do [ "$(basename "$repo")" = "$init_name" ] && targets=("$repo"); done
  [ ${#targets[@]} -eq 1 ] || { printf '\nrepos.sh: no repo named %s in the fleet\n' "$init_name"; exit 1; }
fi

verb=$cmd; [ "$action" = init ] && verb='tag'
go=() news=()
printf '\n%s=== plan: %s ===%s\n' "$BOLD" "$cmd" "$RST"
for repo in "${targets[@]}"; do
  "plan_$action" "$repo"
  if [ "$P_OK" -eq 1 ]; then
    printf '  %s  %s\n' "$(basename "$repo")" "$P_DESC"; go+=("$repo"); news+=("${P_NEW:-}")
  else
    printf '  %s%s  %s%s\n' "$DIM" "$(basename "$repo")" "$P_DESC" "$RST"
  fi
done

if [ ${#go[@]} -eq 0 ]; then
  printf '\nnothing to %s\n' "$verb"
  [ "$action" = init ] && exit 1 || exit 0
fi
if [ "$yes" -ne 1 ]; then
  noun=repos; [ ${#go[@]} -eq 1 ] && noun=repo
  printf '\n'
  printf '%s %s %s? [y/N] ' "$verb" "${#go[@]}" "$noun"   # printed, not read -p: shown even when piped
  read -r answer || answer=''
  [[ $answer == [yY] || $answer == [yY][eE][sS] ]] || { echo 'nothing done'; exit 0; }
fi
printf '\n%s=== %s ===%s\n' "$BOLD" "$cmd" "$RST"
for k in "${!go[@]}"; do
  printf '%s%s%s\n' "$BOLD" "$(basename "${go[$k]}")" "$RST"
  case "$action" in
    push)     do_push "${go[$k]}" ;;
    tag|init) do_tag "${go[$k]}" "${news[$k]}" ;;
  esac
done
