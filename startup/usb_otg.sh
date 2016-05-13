#!/bin/sh
# $Rev: 342 $

while [ "$(cat /sys/class/gpio/pioA8/value)" = 0 ]; do
  if [ "$(cat /tmp/viusb)" = 0 ] &&
     [ "$(cat /sys/class/gpio/pioA14/value)" = 0 ]; then
    #Enable LOW to PA14 to provide 5V to device connected to Modem
    echo out > /sys/class/gpio/pioA14/direction
    echo 1 > /sys/class/gpio/pioA14/value
  fi
  #Turn off Charger if there is no external power
  if [ "$(cat /sys/class/gpio/pioA12/value)" = 0 ]; then
    echo none > /sys/class/leds/CHG_CE/trigger
  fi
  break
done

while [ "$(cat /sys/class/gpio/pioA8/value)" = 1 ]; do
  #Enable charger
  echo default-on > /sys/class/leds/CHG_CE/trigger
  #Enable HIGH to PA14 to disable 5V out
  echo in > /sys/class/gpio/pioA14/direction
  #Clear viusb connection to be ready for otg device
  echo 0 > /tmp/viusb
  break
done
