export ENABLE_CITYBANNER="false"

function before_command()
{
	if [[ $ENABLE_CITYBANNER -ne "false" ]]; then
		readarray -t checklist < ~/citybanner/excludes
		for pattern in "${checklist[@]}"; do
			if [[ $BASH_COMMAND == $pattern* ]]; then
				return
			fi
		done
		python3 ~/citybanner/citybanner.py
	fi
}

trap before_command DEBUG



