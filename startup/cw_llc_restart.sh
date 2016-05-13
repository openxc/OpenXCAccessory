#!/bin/sh
### BEGIN INIT INFO
#  Script to
#  1.  start the Cohda device by enablin the gpio - Startup.sh
#  2. Dowloads the firmware into Cohda module
#  3. Inserts the new kernel module for llc
#  4. sets the llc link
### END INIT INFO


PATH=/sbin:/bin:/usr/sbin:/usr/bin
DFU=/usr/bin/dfu-util
ENSCR=/root/startup.sh
#FWPATH=/root/OpenXCAccessory/cohda/kernel/drivers/cohda/llc/SDRMK5Dual.bin
#MODPATH=/root/OpenXCAccessory/cohda/kernel/drivers/cohda/llc/cw-llc.ko
FWPATH=/root/cohda/kernel/drivers/cohda/llc/SDRMK5Dual.bin
MODPATH=/root/cohda/kernel/drivers/cohda/llc/cw-llc.ko
INSMOD=/sbin/insmod
#------------------------------------------------
# map from MAC ID to device id
#------------------------------------------------
#--------------------------------------------
devmap_1=2100
devmap_2=3518
devmap_3=3545
devmap_4=3551
devmap_5=4954
devmap_6=4966
devmap_7=5648
devmap_8=5683
devmap_9=6151
devmap_10=6172
devmap_11=6909
devmap_12=7557
devmap_13=7569
devmap_14=9200
devmap_15=0433
devmap_16=0895
devmap_17=1FC2
devmap_18=1FF8
devmap_19=351E
devmap_20=3A00
devmap_21=3A18
devmap_22=3A30
devmap_23=3A36
devmap_24=494E
devmap_25=495A
devmap_26=4F12
devmap_27=4F18
devmap_28=4F45
devmap_29=521B
devmap_30=56E3
devmap_31=56E9
devmap_32=59B0
devmap_33=63BF
devmap_34=63EC
devmap_35=63F8
devmap_36=65A4
devmap_37=65AA
devmap_38=65B0
devmap_39=65BF
devmap_40=65CB
devmap_41=65E3
devmap_42=65FB
devmap_43=690F
devmap_44=6D00
devmap_45=6D1E
devmap_46=6D3C
devmap_47=6D5D
devmap_48=755D
devmap_49=756F
devmap_50=F6BF
devmap_51=691B
devmap_52=3FEC
devmap_53=6D3C
devmap_54=56E9
devmap_55=4F3C
#--------------------------------------------

setup_ip_mac_addr()
{
    for i in $(seq 1 $2)
    do
    current_value=$1$i
#    echo $(eval echo \$$current_value)
    mac=$(eval echo \$$current_value)
#    echo "mac = $mac"
    if [ "$mac" = $3 ]; then
       echo $i
       echo "setup_link $i" 
       setup_link $i 
#       echo "add_neighborhood $i" 
       add_neighborhood $i 
    fi
    done
    return $i
}


setup_cohda_env()
{
   mac=`hcitool dev | awk '/hci0/ {print $2}'`
   id=`echo $mac | awk -F : '{print $5$6}'`
#   echo $id
   setup_ip_mac_addr devmap_ 55 $id
}


#--------------------------------------------
# Enable COHDA module
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
 
 base_mac="1A:2B:D2:D1:D8:"

 while [ $i -le 55 ]
 do
   if [ $i -ne $1 ]
   then
       if [ $i -lt 10 ]
       then
         j="0$i"
       else
         j=$i
       fi
#       echo "ip neigh replace 10.0.0.$i lladdr $base_mac$j dev cw-llc"
       ip neigh replace 10.0.0.$i lladdr $base_mac$j dev cw-llc
   fi
       i=`expr $i + 1`
 done

}
#------------------------------------------
# setup link
#------------------------------------------
setup_link() {

base_ip="10.0.0."
base_mac="1A:2B:D2:D1:D8:"

if [ $1 -lt 10 ]
then
   j="0$1"
else
   j=$1
fi
 
 

echo "ip link set cw-llc mtu 1500"
ip link set cw-llc mtu 1500

#ip link set dev cw-llc address 1A:2B:D2:D1:D8:01
echo "ip link set dev cw-llc address $base_mac$j"
ip link set dev cw-llc address $base_mac$1

echo "ip link set cw-llc up"
ip link set cw-llc up

echo "cd /root/OpenXCAccessory/cohda/app/llc"
cd /root/cohda/app/llc

#/root/OpenXCAccessory/cohda/app/llc/llc  chconfig -s -w SCH -c 184 -r a -e 0x88b6 -a 3 -f 1A:2B:D2:D1:D8:01
echo "/root/cohda/app/llc/llc  chconfig -s -w SCH -c 184 -r a -p -10 -e 0x88b6 -a 3 -f $base_mac$j"
/root/cohda/app/llc/llc  chconfig -s -w SCH -c 184 -r a -p -10 -e 0x88b6 -a 3 -f $base_mac$j

#ifconfig cw-llc 10.0.0.1
echo "ifconfig cw-llc $base_ip$1"
ifconfig cw-llc $base_ip$1
}
#######################################################
# Main Script
#######################################################
setup_cohda_env


