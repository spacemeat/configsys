#!/bin/bash

if [ -e ~/.ssh/id_ed25519.pub ] ; then
	echo "~/.ssh/id_ed25519.pub is already."
	exit 0
fi
run 'ssh-keygen -t ed25519 -C "spacemeat@gmail.com"' || exit $?
run 'eval "$(ssh-agent -s)"' || exit $?
run 'ssh-add ~/.ssh/ed25519' || exit $?
run 'cat ~/.ssh/ed25519.pub | setclip' || exit $?
echo "Public key has been set to the clipboard."
run 'xdg-open https://github.com/settings/keys' || exit $?

