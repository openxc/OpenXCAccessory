#!/bin/bash

# $Rev: 246 $
# $Author: mlgantra $
# $Date: 2015-04-07 12:57:25 -0700 (Tue, 07 Apr 2015) $

# 
# GSM utility
# It return 0 as succesful status and use gsmlog as communication interface
#

function usage {
  cat <<EOU

  Simple script to handle GPS module

Usage: $0 <options>

  where options are
    -a : attention check
    -c : contact activation check
    -f : turn off contact activation
    -o : turn on contact activation
    -p : contact activation preparation
    -r : setup Telit reset pin (pA6) 
    -R : setup Telit 3.3V enable pin (pA4) 
    -w : wait for specified device
    -s : start ppp connection
    -k : kill ppp connection
    -h : display this menu

EOU
  exit 1
}


if [ -e /root/OpenXCAccessory/common/.xcmodem_boardid ]; then
  id=`cat /root/OpenXCAccessory/common/.xcmodem_boardid`
  if [ "$id" -ge "2" ]; then
    echo "INFO:xcmodem:Board V2X"
    echo "ERROR:xcmodem:V2X doesn't support GSM"
    exit 1
  fi
fi

[ $# -gt 0 ] || usage

max_attempt=3
max_waittime=60

prog="$0"
check=0
ppp=0
start=0
prep=0
while getopts "acfhkop:r:R:sw:" opt; do
    case $opt in
        a)
            cmd='AT\r'
            key='OK'
            ;;
        c)
            check=1
            cmd='AT#SGACT?\r'
            key='SGACT'
            ;;
        o)
            cmd='AT#SGACT=1,1\r'
            key='OK'
            ;;
        f)
            cmd='AT#SGACT=1,0\r'
            key='OK'
            ;;
        p)
            prep=1
            APN=${OPTARG}
            ;;
        r)
            if ! [ -d  /sys/class/gpio/pioA6 ]; then
                echo 6   > /sys/class/gpio/export
                echo out > /sys/class/gpio/pioA6/direction
            fi
            val=${OPTARG}
            echo $val > /sys/class/gpio/pioA6/value
            exit 0
            ;;
        R)
            if ! [ -d  /sys/class/gpio/pioA4 ]; then
                echo 4   > /sys/class/gpio/export
                echo out > /sys/class/gpio/pioA4/direction
            fi
            val=${OPTARG}
            echo $val > /sys/class/gpio/pioA4/value
            exit 0
            ;;
        w)
            cnt=1    
            dev=${OPTARG}
            while [ $cnt -le $max_waittime ]
                do 
                    if ! [ -e $dev ]; then
                        echo " been waiting for $cnt secs"
                        cnt=$[$cnt + 1]
                        sleep 1
                    else
                        exit 0
                    fi
                done
            exit 1
            ;;
        s)
            ppp=1
            start=1
            ;;
        k)
            ppp=1
            ;;
        *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))


function killsub () {
    kill -9 ${1} 2>/dev/null
    wait ${1} 2>/dev/null
}

attempt=1
if [ $prep == 1 ]; then
    # clean up lingering pppd process if exist
    killall -q pppd
    while [ $attempt -le $max_attempt ]; do
        # activation check
        $prog -c
        grep 'SGACT: 1,0' gsmlog
        if [ $? == 0 ]; then
            # setup CGD Contact
            echo -e "AT+CGDCONT=1,\"IP\",\"${APN}\"\\r" > /dev/ttyACM3
            exit 0
        fi
        # turn off contact activation
        $prog -f
        attempt=$[$attempt+1]
    done
    exit 1
elif [ $ppp == 1 ]; then
    if [ $start == 1 ]; then
        # invoke pppd daemon
        pppd file /etc/pppd_script &
        attempt=1
        while [ $attempt -le $max_attempt ]; do
            sleep 10
            ifconfig | grep ppp0
            if [ $? == 0 ]; then
                route add default ppp0
                exit 0
            fi
            attempt=$[$attempt+1]
        done
        exit 1
    else
        # bring ppp0 down should kill all process
        killall -q pppd
        exit 0
    fi
else
    if [ $check == 1 ]; then
        $prog -a
        if [ $? == 0 ]; then
            # setup a CGD first
            echo -e 'AT+CGDCONT=1,"IP","apn"\r' > /dev/ttyACM3
        else                
            exit 1
        fi
    fi
    echo -e "ATE=0\r" > /dev/ttyACM3
    cat -u /dev/ttyACM3 > gsmlog &
    sleep 1
    echo -e $cmd > /dev/ttyACM3
    sleep 1 
    pid=`ps a | awk '/cat -u \/dev\/ttyACM3/ {print $1}'`
    killsub $pid
    grep "$key" gsmlog
    if [ $? == 0 ]; then
        exit 0
    fi
fi
exit 1
