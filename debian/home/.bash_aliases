if [ -d ~/.bash_d ]; then
	for shfile in ~/.bash.d/*.sh; do
		if [ -x $shfile ]; then
			source $shfile
		fi
	done
fi

