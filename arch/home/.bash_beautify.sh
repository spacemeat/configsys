#!/bin/bash

#!/bin/bash
#
# File: .bash_beautify
# Author: Chris Albrecht, @ChrisAlbrecht
#
# Provides color and bash prompt customizations to integrate with SVN and GIT.
export DULL=0
export BRIGHT=1

export FG_BLACK=30
export FG_RED=31
export FG_GREEN=32
export FG_YELLOW=33
export FG_BLUE=34
export FG_VIOLET=35
export FG_CYAN=36
export FG_WHITE=37

export FG_NULL=00

export BG_BLACK=40
export BG_RED=41
export BG_GREEN=42
export BG_YELLOW=43
export BG_BLUE=44
export BG_VIOLET=45
export BG_CYAN=46
export BG_WHITE=47

export BG_NULL=00

##
# ANSI Escape Commands
##
ESC="\001\033"
M="m\002"
NORMAL="$ESC[$M"
RESET="$ESC[${DULL};${FG_WHITE};${BG_NULL}$M"

##
# Shortcuts for Colored Text ( Bright and FG Only )
##

# DULL TEXT
export BLACK="$ESC[${DULL};${FG_BLACK}$M"
export RED="$ESC[${DULL};${FG_RED}$M"
export GREEN="$ESC[${DULL};${FG_GREEN}$M"
export YELLOW="$ESC[${DULL};${FG_YELLOW}$M"
export BLUE="$ESC[${DULL};${FG_BLUE}$M"
export VIOLET="$ESC[${DULL};${FG_VIOLET}$M"
export CYAN="$ESC[${DULL};${FG_CYAN}$M"
export WHITE="$ESC[${DULL};${FG_WHITE}$M"

# BRIGHT TEXT
export BRIGHT_BLACK="$ESC[${BRIGHT};${FG_BLACK}$M"
export BRIGHT_RED="$ESC[${BRIGHT};${FG_RED}$M"
export BRIGHT_GREEN="$ESC[${BRIGHT};${FG_GREEN}$M"
export BRIGHT_YELLOW="$ESC[${BRIGHT};${FG_YELLOW}$M"
export BRIGHT_BLUE="$ESC[${BRIGHT};${FG_BLUE}$M"
export BRIGHT_VIOLET="$ESC[${BRIGHT};${FG_VIOLET}$M"
export BRIGHT_CYAN="$ESC[${BRIGHT};${FG_CYAN}$M"
export BRIGHT_WHITE="$ESC[${BRIGHT};${FG_WHITE}$M"

# REV TEXT as an example
export REV_CYAN="$ESC[${DULL};${BG_WHITE};${BG_CYAN}$M"
export REV_RED="$ESC[${DULL};${FG_YELLOW}; ${BG_RED}$M"

##
# Parse the GIT and SVN branches we may be on
##
function vcs_branch {
  local GIT=$(git_branch)
  local SVN=$(svn_branch)
  if [ -n "$GIT" ]; then
    local BRANCH="${BLUE}$GIT${NORMAL}"
  fi
  if [ -n "$SVN" ]; then
    if [ -n "$GIT" ]; then
      BRANCH="$BRANCH|${BLUE}$SVN${NORMAL}"
    else
      BRANCH="${BLUE}$SVN${NORMAL}"
    fi
  fi
  if [ -n "$BRANCH" ]; then
    echo -e "${WHITE}(${BRANCH}${WHITE})"
  fi
}

##
# Get the current GIT branch
##
function git_branch {
  ref=$(git symbolic-ref HEAD 2> /dev/null) || return
  echo ${ref#refs/heads/}
}

##
# Get the current SVN branch
##
function svn_branch {
  if [ ! -d .svn ]; then
    exit 1
  fi

  # Get the current URL of the SVN repo
  URL=`svn info --xml | fgrep "<url>"`

  # Strip the tags
  URL=${URL/<url>/}
  URL=${URL/<\/url>/}

  # Find the branches directory
  if [[ "$URL" == */trunk ]]; then
    DIR=${URL//\/trunk*/}
  fi
  if [[ "$URL" == */tags/* ]]; then
    DIR=${URL//\/tags*/}
  fi
  if [[ "$URL" == */branches/* ]]; then
    DIR=${URL//\/branches*\/*/}
  fi
  DIR="$DIR/branches"

  # Return the branch name
  if [[ "$URL" == */trunk* ]]; then
    echo 'trunk'
  elif [[ "$URL" == */branches/* ]]; then
    echo $URL | sed -e 's#^'"$DIR/"'##g' | sed -e 's#/.*$##g' | awk '{print ""$1"" }'
  fi
}

# Set the prompt pattern
export PS1="${BRIGHT_RED}[${BLUE}\u${VIOLET}@${BRIGHT_VIOLET}\h\$(vcs_branch)${WHITE}: \w${BRIGHT_RED}]${NORMAL} \$ "

