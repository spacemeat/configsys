#!/usr/bin/bash

res=randr | grep \* | awk '{print $1}'
sleepTime=${1:-'5'}
while true
do
	cmp=randr | grep \* | awk '{print $1}'
	if [ res != cmp ] ; then
		nitrogen --restore
	fi	
	sleep $sleepTime
done
