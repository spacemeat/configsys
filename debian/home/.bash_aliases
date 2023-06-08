#alias g="python3 -m boilermaker ./og-boma.hu"
#alias b="python3 -m boilermaker ./build.hu; python3 -m geg"
#alias d="python3 -m geg"
alias gdb="gdb -x ~/.gdbinit_x"

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

