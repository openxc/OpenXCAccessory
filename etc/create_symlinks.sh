#!/bin/bash

# This script removes the existing files in /etc which are to be housed within the OpenXCAccessory repository.  The files are then replaced by symbolic links to the new versions within /root/OpenXCAccessory/etc

rm /etc/wpa_supplicant_*	# Remove the existing supplicant files in /etc to make way for symlinks
ln -s /root/OpenXCAccessory/etc/wpa_supplicant_modem.conf /etc/wpa_supplicant_modem.conf
ln -s /root/OpenXCAccessory/etc/wpa_supplicant_rsu.conf /etc/wpa_supplicant_rsu.conf
ln -s /root/OpenXCAccessory/etc/wpa_supplicant_v2x.conf /etc/wpa_supplicant_v2x.conf
ln -s /root/OpenXCAccessory/etc/wpa_supplicant_v2x_top2.conf /etc/wpa_supplicant_v2x_top2.conf
rm -r /etc/init.d
ln -s /root/OpenXCAccessory/etc/init.d/ /etc/init.d
rm /etc/rc.local
ln -s /root/OpenXCAccessory/etc/rc.local /etc/rc.local
rm /etc/pppd_script
ln -s /root/OpenXCAccessory/startup/pppd_script /etc/pppd_script
