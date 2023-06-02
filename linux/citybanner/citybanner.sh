#!/bin/bash

BC="\xe2\x96\x84"

function min()
{
	echo $(( $1 < $2 ? $1 : $2 ))
}

# h (0-255) s (0-255) v (0-255)
function hsv2rgb()
{
	local h=$(( $1 + 0 ))
	local s=$(( $2 + 0 ))
	local v=$(( $3 + 0 ))

	#echo "h:$h s:$s v:$v; "

	if [[ $s == 0 ]]; then
		echo -e "$v $v $v"
	else
		local region=$(( $h / 43 ))
		local m=$(( ($h - $region * 43) * 6))

		local p=$(( (($v * (255 - $s)) / 256) % 256 ))
		local q=$(( (($v * (255 - (($s * $m) / 256))) / 256) % 256 ))
		local t=$(( (($v * (255 - (($s * (255 - $m)) / 256))) / 256) % 256 ))

		case $region in
			0)
				echo "$v $t $p"
				;;
			1)
				echo "$q $v $p"
				;;
			2)
				echo "$p $v $t"
				;;
			3)
				echo "$p $q $v"
				;;
			4)
				echo "$t $p $v"
				;;
			5)
				echo "$v $p $q"
				;;
		esac
	fi
}


function color_rgb()
{
	echo -e "\033[48;2;$1;$2;$3m\033[38;2;$4;$5;$6m"
}

function color()
{
	local rgb1=$(hsv2rgb $1 $2 $3)
	local rgb2=$(hsv2rgb $4 $5 $6)
	echo -e "$(color_rgb $rgb1 $rgb2)"
}

function nocolor()
{
	echo -e "\033[m"
}

# r1, g1, b1, r2, g2, b2
function color_block()
{
	echo -e "$(color $1 $2 $3 $4 $5 $6)$BC"
}

function random_color()
{
	local h=$(( $RANDOM % 256 ))
	local s=$(( $RANDOM % 256 ))
	local v=$(( $RANDOM % 256 ))
	echo "$h $s $v"
}

function lerp_colors()
{
	local h1=$1
	local s1=$2
	local v1=$3
	local h2=$4
	local s2=$5
	local v2=$6
	local lerp=$7
	local maxLerp=$8

	local h=$(( ($h2 * $lerp + $h1 * ($maxLerp - $lerp)) / $maxLerp ))
	local s=$(( ($s2 * $lerp + $s1 * ($maxLerp - $lerp)) / $maxLerp ))
	local v=$(( ($v2 * $lerp + $v1 * ($maxLerp - $lerp)) / $maxLerp ))

	echo "$h $s $v"
}

function col_h()
{
	echo "$1"
}

function col_s()
{
	echo "$2"
}

function col_v()
{
	echo "$3"
}

function draw_city()
{
	local num_rows=8
	local num_pixel_rows=$(( $num_rows * 2 ))
	local num_cols=$(( $COLUMNS ))
	local num_bldgs=$(( $RANDOM % 100 + 40 ))

	local heights=() # count = num_cols
	local raster=() # count = num_cols * num_pixel_rows
	local winraster=() # count = num_cols * num_pixel_rows
	local wincolorraster=() # count = num_cols * num_pixel_rows

	local c1=$(random_color)
	local c2=$(random_color)

	for (( i=0; i<$num_cols; i++ ))
	do
		heights+=( 0 )
	done

	for (( b=0; b<$num_bldgs; b++ ))
	do
		local w=$(( $RANDOM % 4 + 1 ))
		local gcap=$(( $(col_v $c1) / 4 + 1 )) # grayscale max depends on top color v
		local g=$(( $RANDOM % $gcap ))
		local gs="0 0 $g"
		local xs=$(( $RANDOM % ($num_cols + $w) - $w ))
		local xe=$(( $xs + $w ))
		local h=$(( $RANDOM % ($num_pixel_rows - 2) + 1 ))
		local window=$(( $RANDOM % 17 ))
		local wincolor="43 $(( $RANDOM % 100 )) $(( 255 - $(col_v $c1) ))"
		local wingl=' '
		if [[ $window == 0 ]]; then
			wingl='.'
		elif [[ $window == 1 ]]; then
			wingl='-'
		elif [[ $window == 2 ]]; then
			wingl='='
		elif [[ $window == 3 ]]; then
			wingl='_'
		elif [[ $window == 4 ]]; then
			wingl="\xe2\x96\x96"
		elif [[ $window == 5 ]]; then
			wingl="\xe2\x96\x97"
		elif [[ $window == 6 ]]; then
			wingl="\xe2\x94\x85"
		elif [[ $window == 7 ]]; then
			wingl="\xe2\x94\x87"
		elif [[ $window == 8 ]]; then
			wingl="\xe2\x95\xba"
		elif [[ $window == 9 ]]; then
			wingl="\xe2\x95\x8f"
		elif [[ $window == 10 ]]; then
			wingl="\xe2\x94\x8b"
		elif [[ $window == 11 ]]; then
			wingl="\xe2\x95\x8d"
		elif [[ $window == 12 ]]; then
			wingl="\xe2\x96\xaa"
		elif [[ $window == 13 ]]; then
			wingl="\xe2\x97\xbc"
		elif [[ $window == 14 ]]; then
			wingl="\xe2\x96\xac"
		elif [[ $window == 16 ]]; then
			wingl="\xe2\x96\xae"
		fi

		for (( y=$(( $num_pixel_rows - $h )); y<$num_pixel_rows; y++ ))
		do
			for (( x=$xs; x<$xe; x++ ))
			do
				if [[ ${heights[$x]} -lt $h ]]; then
					heights[$x]=$h
				fi
				if [[ $x -ge 0 && $x -lt $num_cols ]]; then
					local idx=$(( $y * $num_cols + $x ))
					raster[$idx]=$gs
					winraster[$idx]=$wingl
					wincolorraster[$idx]=$wincolor
				fi
			done
		done
	done

	for (( i=0; i<$num_rows; i++ )) 
	do
		local cmemo="."
		local rowA=$(( i * 2 ))
		local rowB=$(( i * 2  + 1 ))
		local skyColorA=$(lerp_colors $c1 $c2 $rowA $(($num_pixel_rows - 1)))
		local skyColorB=$(lerp_colors $c1 $c2 $rowB $(($num_pixel_rows - 1)))
		for (( j=0; j<$num_cols; j++ ))
		do
			local canWindow=0
			local cr1=""
			if [[ $(( $num_pixel_rows - $rowA )) -le "${heights[$j]}" ]]; then
				cr1=${raster[$(( $rowA * $num_cols + $j ))]}
				canWindow=1
			else
				cr1=$skyColorA
			fi
			local cr2=""
			if [[ $(( $num_pixel_rows - $rowB )) -le "${heights[$j]}" ]]; then
				if [[ $canWindow -ne 1 ]]; then
					cr2=${raster[$(( $rowB * $num_cols + $j ))]}
					canWindow=0
				else
					canWindow=2
					if [[ $(( $RANDOM % 2 )) -eq 1 ]]; then
						cr2="0 0 0"
					else
						cr2="${wincolorraster[$(( $rowB * num_cols + $j ))]}"
					fi
				fi
			else
				cr2=$skyColorB
			fi
			local colpr="$(color $cr1 $cr2)"
			if [[ $colpr != $cmemo ]]; then
				cmemo=$colpr
				printf "$colpr"
			fi
			if [[ $canWindow -eq 2 ]]; then
				printf "${winraster[$(( $rowA * $num_cols + $j ))]}"
			else
				printf "$BC"
			fi
		done
		printf "$(nocolor)\n"
	done
}

function testit()
{
	local c1=$(random_color)
	local c2=$(random_color)

	echo -e "$c1; $c2"

	echo -e "$(lerp_colors $c1 $c2 0 5)"
	echo -e "$(lerp_colors $c1 $c2 1 5)"
	echo -e "$(lerp_colors $c1 $c2 2 5)"
	echo -e "$(lerp_colors $c1 $c2 3 5)"
	echo -e "$(lerp_colors $c1 $c2 4 5)"
}

#echo -e "$(draw_city)"
#echo -e "$(nocolor)"

cachePath="$HOME/citybanner/cache"
cacheDir="$HOME/citybanner"

echo $cacheDir
ls $cacheDir

[[ ! -d $cacheDir ]] && echo "wtf" # mkdir $(dirname $cachePath)

if [[ -f $cachePath ]]; then
	echo -e "$(cat $cachePath)"
else
	echo -e "$(draw_city)"
fi

touch $cachePath
echo -e "$(draw_city)" > $cachePath &

