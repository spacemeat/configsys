BASH_D=~/.bash.d
if [ -d $BASH_D ]; then
	for shfile in $BASH_D/*.sh; do
		if [ -x $shfile ]; then
			echo "Sourceing $shfile..."
			source $shfile
			echo "... done."
		fi
	done
fi

