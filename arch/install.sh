echo "Is this installed as a VirtualBox guest? Y/n"
read isVboxGuest

timedatectl set-ntp true

pacman -Sq --needed --noconfirm vim tree build-devel git python pip xf86-video-fbdev xorg xorg-xinit nitrogen picom firefox alacritty openbox obconf menumaker tint2 rofi

if [[ $isVboxGuest == [yY] || $isVboxGuest == [yY][eE][sS] ]]; then
	pacman -Sq --needed --noconfirm virtualbox-guest-utils
	systemctl enable vboxservice.service
fi

# get paru for getting AUR packages
if [ -n "$(pacman -Q paru)" ]; then
	cd ~
	git clone https://aur.archlinux.org/paru.git
	cd paru
	makepkg -si
fi

# get AUR packages, mostly for openbox
cd ~
paru -Sq openbox-themes obtheme obmenu obkey obapps

# put configuration files where they go for great justice
. $(dirname "$0")/dotfiles.sh out

