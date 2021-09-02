#
# ~/.bashrc
#

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

alias ls='ls --color=auto'

function joinBy()
{
	local IFS="$1"
	shift
	echo "$*"
}

function before_command()
{
	readarray -t checklist < ~/citybanner/excludes
	for pattern in "${checklist[@]}"; do
		if [[ $BASH_COMMAND == $pattern* ]]; then
			return
		fi
	done
	python ~/citybanner/citybanner.py $COLUMNS $LINES
}

trap before_command DEBUG

. ~/.bash_beautify.sh
# PS1='[\u@\h \W]\$ '
