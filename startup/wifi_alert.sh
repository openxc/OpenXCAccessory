#!/bin/sh 
# $Rev: 423 $

set +x

wlan0_search=`cat /proc/net/dev | grep wlan0 | wc -l`
if [ $wlan0_search -eq 0 ]; then
        echo "===>>> Missing WLAN0 interface."
        echo "===>>> Please restart your system !"
fi
