alias d="python3 -m geg"
alias gdb="gdb -x ~/.gdbinit_x"

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

