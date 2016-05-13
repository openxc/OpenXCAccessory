#!/bin/sh 
# $Rev: 423 $

set +x

while (sleep 30 && /root/OpenXCAccessory/startup/wifi_led) &
do
  wait $!
done
