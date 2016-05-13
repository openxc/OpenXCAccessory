#!/bin/sh
# $Rev: 245 $

while (sleep 3 && sh /root/OpenXCAccessory/startup/usb_otg.sh) &
do
  wait $!
done
