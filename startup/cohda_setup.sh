#!/bin/sh
### BEGIN INIT INFO
#  Script to
#  1. start the Cohda device by enablin the gpio 
#  2. Dowloads the firmware into Cohda module
#  3. Inserts the new kernel module for llc
#  4. sets the llc link
### END INIT INFO

#---------------------------------------------
# Path setup 
#---------------------------------------------
PATH=/sbin:/bin:/usr/sbin:/usr/bin
DFU=/usr/bin/dfu-util
FWPATH=/root/cohda/kernel/drivers/cohda/llc/SDRMK5Dual.bin
MODPATH=/root/cohda/kernel/drivers/cohda/llc/cw-llc.ko
INSMOD=/sbin/insmod

#---------------------------------------------
# Networking setup variable
#---------------------------------------------
DEVICE_COUNT=62
BASE_MAC="1A:2B:D2:D1:D8:"
BASE_IP="10.0.0."

#----
#source the device map
#----
. /root/OpenXCAccessory/startup/device_maptable.sh
#--------------------------------------------

#------------------------------------------------------
# Call the ip and mac addresses and setup neighborhood
#------------------------------------------------------
setup_ip_mac_addr()
{
    for i in $(seq 1 $2)
    do
    current_value=$1$i
    mac=$(eval echo \$$current_value)
    if [ "$mac" = $3 ]; then
       echo $i
       #echo "setup_link $i" 
       setup_link $i 
       #echo "add_neighborhood $i" 
       add_neighborhood $i 
    fi
    done
    return $i
}


#------------------------------------------------------
# Get the last four letters for the BT MAC Address and 
# use it for getting the sequence number for device to
# setup IP and MAC address 
#------------------------------------------------------
setup_cohda_env()
{
  #----
  #--  Get tha last four letter of BT MAC Address
  #----

   mac=`hcitool dev | awk '/hci0/ {print $2}'`
   id=`echo $mac | awk -F : '{print $5$6}'`

  #----
  #--  setup IP and MAC Address based on last four letters of BT MAC 
  #----
   setup_ip_mac_addr devmap_ $DEVICE_COUNT $id
}


#--------------------------------------------
# Enable COHDA module by setting corresponding
# GPIO pin low
#-------------------------------------------
start_cohda() {
echo "Starting COHDA";
  echo "enabling COHDA module";
  echo 6   > /sys/class/gpio/export    # R2_PERST#
  echo out > /sys/class/gpio/pioA6/direction
  echo 0   > /sys/class/gpio/pioA6/value
}

#--------------------------------------------
# download the Cohda firmware 
# There is not persistent storage in the 
# Cohda module so FW needs to downloaded with
# power up
#-------------------------------------------
download_fw() {
echo "Downloading COHDA FW";
if (test -e $DFU) then
   if (test -e $FWPATH) then
    echo "Downloading COHDA Firmware";
    $DFU  -d 1fc9:0102 -D $FWPATH -R 2>&1
   else
     echo "cant find formware image $FWPATH";
     exit 0;
   fi
else
  echo "can't find dfu-util $DFU";
  exit 0;
fi
}

#--------------------------------------------
# install the kernel module for Cohda 
# This is kernel module withe updates for
# TCP/UDP support
#-------------------------------------------
install_ko () {
echo "Installing llc ko";
if (test -x $INSMOD) then
   if (test -e $MODPATH) then
    echo "Installing cw-llc kernel module ";
    $INSMOD $MODPATH
   else
     echo "cant find moudle $MODPATH";
     exit 0;
   fi
else
  echo "can't find INSMOD $INSMOD";
  exit 0;
fi
}
#--------------------------------------------
# add the neighborhood devices with their IP 
# and MAC addresses. These are pre assigned
#-------------------------------------------
add_neighborhood() {
 i=1
 
 while [ $i -le $DEVICE_COUNT ]
 do
   if [ $i -ne $1 ]
   then
       if [ $i -lt 10 ] 
       then
         j="0$i" # prepend 0 in front of single digit serial numer
       else
         j=$i
       fi

       # add devices other than self in the table to the neighborhood
       ip neigh replace 10.0.0.$i lladdr $BASE_MAC$j dev cw-llc
   fi
       i=`expr $i + 1`
 done

}
#------------------------------------------
# setup link
#------------------------------------------
setup_link() {

if [ $1 -lt 10 ]
then
   j="0$1" # prepend 0 in front of single digit serial numer
else
   j=$1
fi
 
 
#-----
#-- set the MTU for the device
#-----
ip link set cw-llc mtu 1500

#-----
#-- set the MAC Address for the device
#-----
echo "ip link set dev cw-llc address $BASE_MAC$j"
ip link set dev cw-llc address $BASE_MAC$1

#-----
#-- Start the interface
#-----
echo "ip link set cw-llc up"
ip link set cw-llc up

#-----
#-- Set the cohda link properties
#-----
echo "cd /root/OpenXCAccessory/cohda/app/llc"
cd /root/cohda/app/llc

echo "/root/cohda/app/llc/llc  chconfig -s -w SCH -c 184 -r a -p -10 -e 0x88b6 -a 3 -f $BASE_MAC$j"
/root/cohda/app/llc/llc  chconfig -s -w SCH -c 184 -r a -p -10 -e 0x88b6 -a 3 -f $BASE_MAC$j

#ifconfig cw-llc 10.0.0.1
#-----
#-- set the IP address for the interface
#-----
echo "ifconfig cw-llc $BASE_IP$1"
ifconfig cw-llc $BASE_IP$1
}

#######################################################
# Main Script
#######################################################

#------
start_cohda
sleep 5s

#------
download_fw
sleep 15s

#------
install_ko
sleep 5s

#------
setup_cohda_env

