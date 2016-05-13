#!/bin/sh 
# $Rev: 423 $

set +x

if [ -e /root/OpenXCAccessory/common/.xcmodem_boardid ]; then
	id=`cat /root/OpenXCAccessory/common/.xcmodem_boardid`
	if [ "$id" -eq "1" ]; then
	while (sleep 30 && /root/OpenXCAccessory/startup/wifi_status_modem) &
	do
		wait $!
	done
	fi

	if [ "$id" -ge "2" ]; then
	while (sleep 30 && /root/OpenXCAccessory/startup/wifi_status_v2x_rsu) &
        do
                wait $!
        done
        fi
fi
