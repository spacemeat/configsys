hasFiles(){
	test -e "$1"
}


sudo apt update
sudo apt upgrade
sudo apt install python3-pip python3-venv npm git tree vim build-essential cmake wget curl

# node
curl https://raw.githubusercontent.com/creationix/nvm/master/install.sh | bash
mvn install node

# get Vulkan SDK
wget -qO- https://packages.lunarg.com/lunarg-signing-key-pub.asc | sudo tee /etc/apt/trusted.gpg.d/lunarg.asc
sudo wget -qO /etc/apt/sources.list.d/lunarg-vulkan-jammy.list http://packages.lunarg.com/vulkan/lunarg-vulkan-jammy.list
sudo apt update
sudo apt install vulkan-sdk

# citybanner
mkdir -p ~/citybanner
cp -ru ../linux/citybanner/* ~/citybanner

# geg, the gcc error helper
makedir -p ~/src
pushd ~/src
if ! -d geg ; then
	git clone git@github.com:spacemeat/geg.git
fi

# dotfiles
cp ./home/.bash_aliases ~
cp ./home/.gdbinit ~
cp ./home/.gdbinit_x ~


