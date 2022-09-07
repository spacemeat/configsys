sudo apt update
sudo apt upgrade
sudo apt install git tree vim build-essential

hasFiles(){
	test -e "$1"
}


if hasFiles  ~/Downloads/code_* ; then
	shopt -s nullglob
	files=(~/Downloads/code_*)
	shopt -u nullglob
	n=${#files[*]}

	echo "Installing vscode from ${files[n-1]}..."

	sudo apt install ${files[n-1]}
fi

mkdir -p ~/citybanner
cp -ru ../arch/config/citybanner/* ~/citybanner

cp ./.bash_aliases ~

