#!/bin/bash

source basics.sh

bail () {
	echo "Usage: $0 m n"
	echo "where m and n are integers representing a range of gcc versions to install, inclusive."
	exit 1
}

if [ $# -lt 2 ] ; then
	bail; exit $?
fi

if [ $1 -gt 0 ] 2>/dev/null && [ $2 -gt 0 ] 2>/dev/null && [ $1 -lt $2 ] ; then
	echo ""
else
	bail; exit $?
fi

echo "Installing gcc and g++ versions $1 through $2."

run "sudo apt update" || exit $?
run "sudo apt upgrade" || exit $?

for (( i=$1; i<=$2; i++ ))
do
	run "sudo apt install -y gcc-$i g++-$i" || exit $?
	run "sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-$i $i" || exit $?
	run "sudo update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-$i $i" || exit $?
done

echo "Use 'sudo update-alternatives --config gcc' and 'sudo update-alternatives --config g++' to switch compiler version."

