#!/usr/bin/env bash
# repos.sh — status / push / tag across the whole configsys repo fleet.
#
# The fleet is this repo (configsys, the base) plus its `configsys-*` siblings under the same
# parent dir (the plugin repos). With no argument it just REPORTS; the mutating modes are opt-in.
#
# Usage:
#   tools/repos.sh [status]     report each repo: HEAD, ahead/behind origin, latest vX.Y.Z tag,
#                               and any staged/unstaged/untracked files                (read-only)
#   tools/repos.sh push         push each repo's current branch to origin
#   tools/repos.sh tag | tag-patch | tag-minor | tag-major
#                               bump the latest vX.Y.Z tag (patch / minor+reset / major+reset) and
#                               `git push --tags`. ONLY touches repos that ALREADY have a vX.Y.Z tag
#                               — a still-tagless repo (e.g. configsys pre-1.0) is left alone.
#
# Every mode prints the status report first, so you see the state before anything is pushed/tagged.
set -uo pipefail

cmd=${1:-status}
case "$cmd" in
  status|'')            action=report ;;
  push)                 action=push ;;
  tag|tag-patch)        action=tag; kind=patch ;;
  tag-minor)            action=tag; kind=minor ;;
  tag-major)            action=tag; kind=major ;;
  -h|--help|help)       awk 'NR>1 && /^#/{sub(/^# ?/,""); print; next} NR>1{exit}' "$0"; exit 0 ;;
  *) echo "repos.sh: unknown command '$cmd' (try: status | push | tag[-patch|-minor|-major])" >&2; exit 2 ;;
esac

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

# bump <vX.Y.Z> <patch|minor|major> -> new vX.Y.Z (fails on an unparseable tag)
bump() {
  [[ $1 =~ ^v?([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || return 1
  local M=${BASH_REMATCH[1]} m=${BASH_REMATCH[2]} p=${BASH_REMATCH[3]}
  case $2 in
    patch) p=$((p + 1)) ;;
    minor) m=$((m + 1)); p=0 ;;
    major) M=$((M + 1)); m=0; p=0 ;;
  esac
  printf 'v%s.%s.%s' "$M" "$m" "$p"
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

# -- actions -------------------------------------------------------------------------------------
do_push() {
  local repo=$1 br up a
  g "$repo" remote get-url origin >/dev/null 2>&1 || { printf '    %sskip — no origin%s\n' "$YEL" "$RST"; return; }
  br=$(g "$repo" symbolic-ref --short -q HEAD) || { printf '    %sskip — detached HEAD%s\n' "$YEL" "$RST"; return; }
  # nothing to push if the branch isn't ahead of its upstream
  if up=$(g "$repo" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null); then
    a=$(g "$repo" rev-list --count "${up}..HEAD" 2>/dev/null); a=${a:-0}
    [ "$a" -eq 0 ] && { printf '    %sskip — up to date with %s%s\n' "$DIM" "$up" "$RST"; return; }
  fi
  printf '    pushing %s -> origin\n' "$br"
  if g "$repo" push origin "$br"; then printf '    %sok%s\n' "$GRN" "$RST"; else printf '    %sFAILED%s\n' "$RED" "$RST"; fi
}

do_tag() {
  local repo=$1 tag new n
  tag=$(latest_tag "$repo")
  [ -n "$tag" ] || { printf '    %sskip — no existing tags%s\n' "$DIM" "$RST"; return; }
  # nothing to tag if there are no commits since the latest tag
  n=$(g "$repo" rev-list --count "${tag}..HEAD" 2>/dev/null); n=${n:-0}
  [ "$n" -eq 0 ] && { printf '    %sskip — no commits since %s%s\n' "$DIM" "$tag" "$RST"; return; }
  new=$(bump "$tag" "$kind") || { printf '    %sskip — unparseable tag %s%s\n' "$YEL" "$tag" "$RST"; return; }
  if g "$repo" rev-parse -q --verify "refs/tags/$new" >/dev/null 2>&1; then
    printf '    %sskip — %s already exists%s\n' "$YEL" "$new" "$RST"; return
  fi
  # a release tag on unpushed commits is usually a mistake — warn, but proceed (the tag push carries them)
  if up=$(g "$repo" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null); then
    a=$(g "$repo" rev-list --count "${up}..HEAD" 2>/dev/null)
    [ "${a:-0}" -gt 0 ] && printf '    %snote — %s commit(s) not on %s yet (consider: repos.sh push)%s\n' "$YEL" "$a" "$up" "$RST"
  fi
  printf '    tagging %s -> %s\n' "$tag" "$new"
  if g "$repo" tag "$new" && g "$repo" push origin --tags; then
    printf '    %sok%s\n' "$GRN" "$RST"
  else
    printf '    %sFAILED%s\n' "$RED" "$RST"
  fi
}

# -- run -----------------------------------------------------------------------------------------
for repo in "${repos[@]}"; do report "$repo"; done

if [ "$action" != report ]; then
  printf '\n%s=== %s ===%s\n' "$BOLD" "$cmd" "$RST"
  for repo in "${repos[@]}"; do
    printf '%s%s%s\n' "$BOLD" "$(basename "$repo")" "$RST"
    case "$action" in
      push) do_push "$repo" ;;
      tag)  do_tag "$repo" ;;
    esac
  done
fi
