#!/bin/bash

function cmd()
{
	echo -e "${fg_gray}$1${fg_default}"
	$1
}

# takes a dir or path to file
function ensure_dir()
{
	echo -e "${fg_yellow}Ensuring dir exists: ${fg_cyan}${1}${fg_default}"
	mkdir -p $1
}

function breathe()
{
	action=$1	# in or out
	installDir=$2
	repoDir=$3
	files=$4

	ensure_dir $installDir
	ensure_dir $repoDir
	
	if [ $action=="in" ]; then
		srcDir=$installDir
		destDir=$repoDir
	else
		srcDir=$repoDir
		destDir=$installDir
	fi

	echo -e "${fg_yellow}Breathing ${action}: ${fg_cyan}${srcDir}/${fg_lt_cyan}${files}${fg_default} -> ${fg_cyan}${destDir}${fg_default}"

	if [ -d "${srcDir}" ]; then
		if [ -n "$(ls -A ${srcDir})" ]; then
			cmd "cp -ru ${srcDir}/${files} ${destDir}/"
		else
			echo -e "${fg_gray}(no files to copy)${fg_default}"
		fi
	fi
}



repo_config_dir="${repo_dir}/config"
repo_home_dir="${repo_dir}/home"
repo_opt_dir="${repo_dir}/opt/scripts"

ensure_dir $repo_config_dir
ensure_dir $repo_home_dir
ensure_dir $repo_opt_dir

# get nitrogen refresh service
breathe $action /opt/scripts $repo_opt_dir nitrogen-check.sh
breathe $action ~/.config/systemd/user $repo_config_dir/systemd/user nitrogen.service

# get nitrogen config
breathe $action ~/.config/nitrogen $repo_config_dir/nitrogen "*"
# Note that particular wallpapers are on a separate repo.

# get themes
breathe $action ~/.config/gtk-2.0 $repo_config_dir/gtk-2.0 "*"
breathe $action ~/.config/gtk-3.0 $repo_config_dir/gtk-3.0 "*"
breathe $action ~/.config/xfce4 $repo_config_dir/xfce4 "*"

# get openbox config
breathe $action ~/.config/openbox $repo_config_dir/openbox "*"

# get thunar config
breathe $action ~/.config/Thunar $repo_config_dir/Thunar "*"

# get xarchiver config
breathe $action ~/.config/xarchiver $repo_config_dir/xarchiver "*"

# get X11 rc
breathe $action ~ $repo_home_dir .xinitrc

