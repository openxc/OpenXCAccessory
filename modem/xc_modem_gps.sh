#!/bin/bash

# $Rev: 246 $
# $Author: mlgantra $
# $Date: 2015-04-07 12:57:25 -0700 (Tue, 07 Apr 2015) $

# 
# GPS acquired position utility
# It return 0 as succesful status and store latest gps information in gpslog
#

function usage {
  cat <<EOU

  Simple script to handle GPS module

Usage: $0 <options>

  where options are
    -a : attention check 
    -c : power check 
    -p : acquire position
    -o : power on
    -f : power off
    -s : start 
    -h : display this menu

EOU
  exit 1
}


if [ -e /root/OpenXCAccessory/common/.xcmodem_boardid ]; then
  id=`cat /root/OpenXCAccessory/common/.xcmodem_boardid`
  if [ "$id" -ge "2" ]; then
    echo "INFO:xcmodem:Board V2X"
    echo "ERROR:xcmodem:V2X doesn't support GPS"
    exit 1
  fi
fi

max_attempt=3

[ $# -gt 0 ] || usage

prog="$0"
start=0
while getopts "acfhops" opt; do
    case $opt in
        a)
            cmd="AT\r"
            key="OK"
            ;;
        c)
            cmd="AT\$GPSP?\r"
            key="GPSP"
            ;;
        p)
            cmd="AT\$GPSACP\r"
            key="GPSACP"
            ;;
        o)
            cmd="AT\$GPSP=1\r"
            key="GPSP: 1"
            ;;
        f)
            cmd="AT\$GPSP=0\r"
            key="GPSP: 0"
            ;;
        s)
            start=1
            ;;
        *)
            usage
            ;;
    esac
done


function killsub () {
    kill -9 ${1} 2>/dev/null
    wait ${1} 2>/dev/null
}

attempt=0
if [ $start != 0 ]; then
    while [ $attempt -le $max_attempt ]; do
        # attention check
        $prog -a
        if [ $? == 0 ]; then 
            # power check
            $prog -c
            if [ $? == 0 ]; then 
                grep "GPSP: 1" gpslog
                if [ $? != 0 ]; then
                    $prog -o
                else
                    exit 0
                fi
            fi
        fi
        attempt=$[$attempt+1]
    done
    exit 1
else
    echo -e "ATE0\r" > /dev/ttyACM0
    sleep 1 
    cat -u /dev/ttyACM0 > gpslog &
    echo -e "$cmd" > /dev/ttyACM0
    sleep 1 
    pid=`ps a | awk '/cat -u \/dev\/ttyACM0/ {print $1}'`
    killsub $pid
    grep "$key" gpslog
    if [ $? == 0 ]; then
        exit 0
    fi
fi
exit 1
