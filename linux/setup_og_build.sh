# We're currently getting the vulkan SDK in standard install.
sudo apt install libglfw3-dev

makedir -p ~/src
pushd ~/src
if ! -d fmt ; then
	wget -O ~/Downloads/fmt-10.0.0.zip https://github.com/fmtlib/fmt/releases/download/10.0.0/fmt-10.0.0.zip
	unzip -d ~/src/fmt ~/Downloads/fmt-10.0.0.zip
	pushd fmt/fmt-10.0.0
	mkdir build
	pushd build
	cmake ..
	make
	sudo make install
	popd ; popd
fi

if ! -d humon ; then
git clone git@github.com:spacemeat/humon.git
fi

if ! -d humon-py ; then
git clone git@github.com:spacemeat/humon-py.git
python3 -m venv .venv -prompt humon-py
pip install -r requirements.txt
deactivate
fi

if ! -d boilermaker ; then
git clone git@github.com:spacemeat/boilermaker.git
python3 -m venv .venv -prompt boilermaker
pip install -e ../humon-py
pip install -r requirements.txt
deactivate
fi

if ! -d og ; then
git clone git@github.com:spacemeat/og.git
python3 -m venv .venv -prompt og
pip install -e ../humon-py
pip install -e ../boilermaker
pip install -r requirements.txt
deactivate
fi

popd

