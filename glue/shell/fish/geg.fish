# geg: personal project — put it on PYTHONPATH and alias its module runner.
if set -q PYTHONPATH
    set -gx PYTHONPATH "$HOME/src/geg/geg:$PYTHONPATH"
else
    set -gx PYTHONPATH "$HOME/src/geg/geg"
end
alias geg "python3 -m geg"
