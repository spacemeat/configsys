if [ $PYTHONPATH ]; then
	export PYTHONPATH=$PYTHONPATH:~/src/geg/geg
else
	export PYTHONPATH=~/src/geg/geg
fi
alias geg="python3 -m geg"

