#!/bin/bash


hasFiles(){
        test -e "$1"
}

run(){
        echo -e "$fg_gray$1$fg_default"
        eval $1
	ret_val=$?
        if [ ! $ret_val -eq 0 ] ; then
                echo -e "Command returned $fg_red$ret_val$fg_default"
		return $ret_val
        fi
	return 0
}


fg_default="\e[39m"

fg_black="\e[30m"
fg_red="\e[31m"
fg_green="\e[32m"
fg_yellow="\e[33m"
fg_blue="\e[34m"
fg_magenta="\e[35m"
fg_cyan="\e[36m"
fg_lt_gray="\e[37m"

fg_gray="\e[90m"
fg_lt_red="\e[91m"
fg_lt_green="\e[92m"
fg_lt_yellow="\e[93m"
fg_lt_blue="\e[94m"
fg_lt_magenta="\e[95m"
fg_lt_cyan="\e[96m"
fg_lt_white="\e[97m"

bg_default="\e[49m"

bg_black="\e[40m"
bg_red="\e[41m"
bg_green="\e[42m"
bg_yellow="\e[43m"
bg_blue="\e[44m"
bg_magenta="\e[45m"
bg_cyan="\e[46m"
bg_lt_gray="\w[47m"

bg_gray="\e[100m"
bg_lt_red="\e[101m"
bg_lt_green="\e[102m"
bg_lt_yellow="\e[103m"
bg_lt_blue="\e[104m"
bg_lt_magenta="\e[105m"
bg_lt_cyan="\e[106m"
bg_lt_white="\e[107m"
