source ../linux/basics.sh


run "sudo apt update" || exit $?
run "sudo apt upgrade" || exit $?
run "sudo apt install python3-pip python3-venv npm git tree vim build-essential cmake wget curl xclip" || exit $?

# node
run "curl https://raw.githubusercontent.com/creationix/nvm/master/install.sh | bash" || exit $?
run "mvn install node" || exit $?

# get Vulkan SDK
run "wget -qO- https://packages.lunarg.com/lunarg-signing-key-pub.asc | sudo tee /etc/apt/trusted.gpg.d/lunarg.asc" || exit $?
run "sudo wget -qO /etc/apt/sources.list.d/lunarg-vulkan-jammy.list http://packages.lunarg.com/vulkan/lunarg-vulkan-jammy.list" || exit $?
run "sudo apt update" || exit $?
run "sudo apt install vulkan-sdk" || exit $?

# citybanner
run "mkdir -p ~/citybanner" || exit $?
run "cp -ru ../linux/citybanner/* ~/citybanner" || exit $?

# geg, the gcc error helper
run "makedir -p ~/src" || exit $?
run "pushd ~/src" || exit $?
if ! -d geg ; then
	run "git clone git@github.com:spacemeat/geg.git" || exit $?
fi

# dotfiles
run "cp ./home/.bash_aliases ~" || exit $?
run "cp ./home/.gdbinit ~" || exit $?
run "cp ./home/.gdbinit_x ~" || exit $?


