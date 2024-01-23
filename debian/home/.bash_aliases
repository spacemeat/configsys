#alias g="python3 -m boilermaker ./og-boma.hu"
#alias b="python3 -m boilermaker ./build.hu; python3 -m geg"
#alias d="python3 -m geg"
alias db="gdb -x ~/.gdbinit_x"

alias setclip="xclip -selection c"
alias getclip="xclip -selection c -o"

function before_command()
{
	readarray -t checklist < ~/citybanner/excludes
	for pattern in "${checklist[@]}"; do
		if [[ $BASH_COMMAND == $pattern* ]]; then
			return
		fi
	done
	python3 ~/citybanner/citybanner.py
}

trap before_command DEBUG

# disable python's virtual environment prompt modification; we roll our own
export VIRTUAL_ENV_DISABLE_PROMPT=1

ps1_hist() {
	echo "\[\033[38;2;0;127;127m\]\!\[\033[00m\]"
}

ps1_dch() {
	[ -n "$debian_chroot" ] && echo "\[\033[38;2;127;63;63m\]chroot:\[\033[38;2;255;127;127m\]$debian_chroot\[\033[00m\] "
}

ps1_uh() {
	echo "\[\033[38;2;255;200;0m\]\u \[\033[38;2;127;100;0m\]\h\[\033[00m\]"
}

ps1_cwd() {
	echo "\[\033[38;2;255;100;0m\\]\w\[\033[00m\]"
}

ps1_lastr() {
	if [ $1 -eq 0 ]; then
		echo "\[\033[38;2;0;255;0m\]\$?\[\033[00m\]"
	else
		echo "\[\033[38;2;255;0;0m\]\$?\[\033[00m\]"
	fi
}

ps1_prompt() {
	echo "\$"
}

ps1_git() {
	repo=$(__git_ps1 "%s")
	[ -n "$repo" ] && echo "\[\033[38;2;0;63;127m\]git:\[\033[38;2;0;127;255m\]$repo\[\033[00m\] "
}

ps1_venv() {
	local venv
	if [ -n "$VIRTUAL_ENV" ]; then
		venv="${VIRTUAL_ENV##*/}"
	else
		venv=''
	fi
	[ -n "$venv" ] && echo "\[\033[38;2;127;63;127m\]venv:\[\033[38;2;255;127;255m\]$venv\[\033[00m\] "
}

ps1_build_prompt() {
	last_stat=$?
    	PS1="`ps1_hist`: `ps1_dch``ps1_uh` `ps1_cwd` `ps1_git``ps1_venv``ps1_lastr \$last_stat` \$ "
}

GIT_PS1_SHOWDIRTYSTATE=1
PROMPT_COMMAND=ps1_build_prompt

