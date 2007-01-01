#!/usr/bin/python -x

# $Rev:: 426           $
# $Author:: mlgantra   $
# $Date:: 2015-06-23 1#$
#
# openXC-Modem Vehicle Interface (VI) agent class and associated functions

import logging
import os.path
import subprocess
import re
import string
import sys
import time
import datetime
import socket
import os
from smbus import SMBus

try: 
    import bluetooth
except ImportError:
    LOG.debug("pybluez library not installed, can't use bluetooth interface")
    bluetooth = None

from xc_common import *
from ota_upgrade import *
import xc_led
import xc_ver


#--------------------------------------------------------------------
# Web upload settings
#--------------------------------------------------------------------
XCMODEM_CONFIG_FILE           = 'xc.conf'
XCMODEM_TRACE_RAW_FILE        = 'vi_trace_raw.json'
XCMODEM_TRACE_RAW_BK_FILE     = 'vi_trace_raw_bk.json'
XCMODEM_TRACE_FILE            = 'vi_trace.json'

XCMODEM_V2X_TRACE_RAW_FILE    = 'v2x_trace_raw.json'
XCMODEM_V2X_TRACE_RAW_BK_FILE = 'v2x_trace_raw_bk.json'
XCMODEM_V2X_TRACE_FILE        = 'v2x_trace.json'

XCMODEM_DATA_MOUNT             = '/mnt/data'
XCMODEM_DATA_DEVICE            = '/dev/mmcblk0'
XCMODEM_DATA_PARTITION         = 'mmcblk0p2'
XCMODEM_DATA_TRACE_PREFIX      = '/mnt/data/vi_trace_raw'

XCMODEM_DATA_V2X_TRACE_PREFIX  = '/mnt/data/v2x_trace_raw'
XCMODEM_DATA_TRACE_SUFFIX      = 'json'


UPLOAD_TIMEOUT_FACTOR = 0.05            # in=7K/s out=140K/s
UPLOAD_OVERHEAD_TIME  = 30              # 30s
TIMEOUT_RC = 124
#--------------------------------------------------------------------

FIRMWARE_RESET_BUTTON_MONITOR_INTERVAL = 5    # in seconds

#---------------------------------------------
def vi_bt_restart(name):
    # restart bluetooth 
    LOG.debug("Re-starting bluetooth ...")

    # terminate BT related apps if applicable using exit flag
    exit_flag['bt_restart'] = 1
    cmd = "/etc/init.d/bluetooth restart; /root/OpenXCAccessory/startup/btrestart; /root/OpenXCAccessory/startup/hci_on"
    try:
        subprocess.call(cmd, shell=True)
    except Exceptions as e:
        LOG.debug("%s %s" % (name, e))
        pass
    else:
        pairing_registration()
    exit_flag['bt_restart'] = 0


def vi_bt5_pair(addr, debug):
    import pexpect

    # Bluetooth 5 client tasks are performed using bluetoothctl
    # Thus, python expected like function will be utilized for this task
    try:
        child = pexpect.spawn('bluetoothctl')
        if debug:
            child.logfile = sys.stdout
        child.expect('.*#')
        child.sendline('agent on')
        child.sendline('pairable on')
        child.sendline('scan on')
        child.expect('.*NEW.* Device %s.*' % addr)
        child.sendline('pair %s' % addr)
        child.expect('.*PIN code:')
        child.sendline('1234')
        child.expect('Pairing successful')
        child.sendline('exit')
    except pexpect.TIMEOUT:
        # Note: Bluez5 registers the device although it fails to pair !!
        # Thus, remove the invalid entry if applicable
        cmd = "bluez-test-device list | grep \"%s\"" % addr
        if not subprocess.call(cmd, shell=True):
            cmd = "bluez-test-device remove %s" % addr
            subprocess.call(cmd, shell=True)
        return False
    else:
        return True

#-------------------------------------------------------------------------------------------
def vi_cleanup():
    LOG.debug("Performing cleanup...")
    # Previous paired VI might incidently take over assigned mb/md
    # app ports; thus, we should clean up old paired devices

    # check if the device has already paired up
    cmd = "for d in `bluez-test-device list | grep -v %s | grep -v %s | awk '/OpenXC-VI-/ {print $1}'`; \
           do bluez-test-device remove $d; done" % (OPENXC_V2X_NAME_PREFIX, OPENXC_MODEM_NAME_PREFIX)
    if subprocess.call(cmd, shell=True):
        LOG.debug("clean up fail")

    # Remove lingering trace file
    cmd = "rm -f %s %s %s" % (XCMODEM_TRACE_RAW_FILE, XCMODEM_TRACE_RAW_BK_FILE, XCMODEM_TRACE_FILE)
    subprocess.call(cmd, shell=True)

    cmd = "rm -f %s %s %s" % (XCMODEM_V2X_TRACE_RAW_FILE, XCMODEM_V2X_TRACE_RAW_BK_FILE, XCMODEM_V2X_TRACE_FILE)
    subprocess.call(cmd, shell=True)

    # clean up lingering pppd process if exist
    subprocess.call('if [ -r /var/run/ppp0.pid ]; then echo "cleanup pppd ..."; killall -q pppd; sleep 3; fi', shell=True)

    # turn off all led - needed to be after pppd cleaning up to free /tty/ACM3 for GSM Led if applicable
    xc_led.all_leds(0)

#---------------------------------------------------------------
# USB connection threads
#---------------------------------------------------------------
class usbSendThread (threading.Thread):
    # don't support usb send so just ignore all entry
    def __init__(self, name, usb, queue, eflag):
        threading.Thread.__init__(self)
        self.name = name
        self.device = usb
        self.queue = queue
        self.eflag = eflag
    def run(self):
        LOG.debug("Starting " + self.name)
        while not exit_flag[self.eflag]:
            while not self.queue.empty():
                try:
                    data = self.queue.get()
                    # print("%s [%s]\n" % (self.name, data))
                    # Ignore all usb write since it somehow halt vi 
                    # dongle stream !!!
                    # self.device.write(data)
                except IOError as e:
                    exit_flag[self.eflag] = 1
                    LOG.debug("%s %s" % (self.name, e))
                    break
            msleep(1)
        LOG.debug("disconnected " + self.name)


class usbRecvThread (threading.Thread):
    def __init__(self, name, usb, queue, eflag):
        threading.Thread.__init__(self)
        self.name = name
        self.device = usb
        self.queue = queue
        self.eflag = eflag
    def run(self):
        LOG.debug("Starting " + self.name)
        while not exit_flag[self.eflag]:
            try:
                data = self.device.read()
                # print("%s [%s]\n" % (self.name, data))
                self.queue.put(data)
            except IOError as e:
                LOG.debug("%s %s" % (self.name, e))
                exit_flag[self.eflag] = 1
                break
        LOG.debug("disconnected " + self.name)


#--------------------------------------------------
# usb modem class
#--------------------------------------------------
# Derived from openxc/sources/usb.py
import usb.core
import usb.util

class xcmodemUsb:
    DEFAULT_VENDOR_ID = 0x1bc4
    DEFAULT_PRODUCT_ID = 0x0001
    DEFAULT_READ_REQUEST_SIZE = 512

    # If we don't get DEFAULT_READ_REQUEST_SIZE bytes within this number of
    # milliseconds, bail early and return whatever we have - could be zero,
    # could be just less than 512. If data is really pumpin' we can get better
    # throughput if the READ_REQUEST_SIZE is higher, but this delay has to be
    # low enough that a single request isn't held back too long.
    DEFAULT_READ_TIMEOUT = 200

    DEFAULT_INTERFACE_NUMBER = 0
    VEHICLE_DATA_IN_ENDPOINT = 2
    VEHICLE_DATA_OUT_ENDPOINT = 5
    LOG_IN_ENDPOINT = 11

    def __init__(self, vendor_id=DEFAULT_VENDOR_ID,
                 product_id=DEFAULT_PRODUCT_ID):
        self.device = None
        devices = usb.core.find(find_all=True, idVendor=vendor_id, idProduct=product_id)
        for device in devices:
            try:
                device.set_configuration()
            except usb.core.USBError as e:
                LOG.error("Skipping USB device: %s", e)
            else:
                self.device = device
                addr = "%.4X:%.4X" % (vendor_id, product_id)
                LOG.info("found VI USB %s" % addr)
                port_mac['vi_app'] = addr
                return
        LOG.debug("VI as USB device isn't detected")

    def valid(self):
        return self.device

    def stop(self):
        usb.util.dispose_resources(self.device)

    def read(self, timeout=None,
             endpoint_address=VEHICLE_DATA_IN_ENDPOINT,
             read_size=DEFAULT_READ_REQUEST_SIZE):
        timeout = timeout or self.DEFAULT_READ_TIMEOUT
        try:
            return self.device.read(0x80 + endpoint_address,
                    read_size, self.DEFAULT_INTERFACE_NUMBER, timeout).tostring()
        except (usb.core.USBError, AttributeError) as e:
            if e.errno == 110:
                # Timeout, it may just not be sending
                return ""
            raise IOError("USB device couldn't be read", e)

    def write(self, data):
        try:
            self.device.write(self.VEHICLE_DATA_OUT_ENDPOINT, data)
        except (usb.core.USBError, AttributeError) as e:
            raise IOError("USB device couldn't be written", e)

#---------------------------------------------------------------------
# class for Modem's VI interface
#---------------------------------------------------------------------
class xcModemVi:
    def __init__(self, port, inQ, outQ, sdebug = 0, debug = 0):
        self.port = port
        self.addr = None
        self.socket = None
        self.discovery_once = False
        self.inQ = inQ
        self.outQ = outQ
        self.fp = None
        self.v2x_fp = None
        self.name = 'vi_app'
        self.trace_enable = 0
        self.v2x_trace_enable = 0
        self.stop_web_upload = None
        self.stop_v2x_web_upload = None
        self.stop_trace = None
        self.stop_monitor = None
        self.stop_button_monitor = None
        self.button_irq_cnt = 1
        self.trace_lock = threading.Lock()
        self.trace_raw_lock = threading.Lock()
        self.v2x_trace_raw_lock = threading.Lock()
        self.threads = []
        self.lost_cnt = 0
        self.gsm = None
        self.bt5 = self.bt5_check()
        self.sdebug = sdebug
        self.debug = debug
        self.boardid = boardid_inquiry(1)
        self.config_mode = None
        self.sd_space = 0
        self.usb = None
	self.modem_ip_addr = None
        self.modem_port = None
        self.conn_type = None
        # LEDs instances
        pathid = self.boardid > 0
        self.bt_led = xc_led.xcModemLed('bt_led', led_path['bt'][pathid])
        self.wifi_led = xc_led.xcModemLed('wifi_led', led_path['wifi'][pathid])
        self.bat_led_grn = xc_led.xcModemLed('bat_led_grn', led_path['bat_grn'][pathid])
        self.bat_led_red = xc_led.xcModemLed('bat_led_red', led_path['bat_red'][pathid])
        modem_state[self.name] = vi_state.IDLE
        self.charger = SMBus(0)   # open Linux device /dev/ic2-0
        self.led_cntl = SMBus(2)  # open Linux device /dev/ic2-2
        self.charger_fault = 0
        self.battery_check()

    def cur_conn_type(self):
        return self.conn_type;

    def modem_mac_inquiry(self):
        # Return modem mac address
        mac = subprocess.check_output('hcitool dev | grep hci0', shell=True).split()[1]
        LOG.info("%s %s" % (board_type[self.boardid]['prefix'], mac))
        return mac


    def bt5_check(self):
        # check if bluetooth 5 is used
        bt_ver = subprocess.check_output("bluetoothd -v | awk -F . '{print $1}'", shell=True).strip()
        LOG.debug('Bluez' + bt_ver)
        return (int(bt_ver) >= 5)


    def auto_discovery(self):
        # Return address once the first openxc device found

        LOG.info("Auto discovery ...")
        try:
            nearby_devices = bluetooth.discover_devices(lookup_names = True)
        except BluetoothError as e:
            LOG.error("BT error %s %s" % (self.name, e))
            return None

        for addr, name in nearby_devices:
            LOG.debug("  %s - %s" % (addr, name))
            if (name is not None \
            and name.startswith(OPENXC_DEVICE_NAME_PREFIX) \
            and not name.startswith(OPENXC_MODEM_NAME_PREFIX) \
            and not name.startswith(OPENXC_V2X_NAME_PREFIX)):
                LOG.info("Found  %s - %s" % (addr, name))
                self.addr = addr
                break
        self.discovery_once = True
        return self.addr


    def file_discovery(self, fname):
        # Return address from existing configuration file

        LOG.info("Static discovery ...")
        brightness_override = 0
        if os.path.exists(fname):
            # setup default based on modem/v2x board
            for key in ['gsm_enable', 'gps_enable', 'openxc_vi_enable', 'openxc_md_enable']:
                conf_options[key] = int(board_type[self.boardid]['type'] != 'V2X')
            try:
                conf = open(fname, "r")
                LOG.info("  Found %s ..." % fname)
                for line in conf:
                    if not line.startswith('#') and line.strip():   # skip comments/blank lines
                        L = line.split()                            # split the string
                        key = L[0]
                        if conf_options.get(key) is not None:       # for valid key
                            LOG.debug("old: (%s:%s)" % (key, conf_options[key]))
                            if key == 'gsm_enable' or key == 'gps_enable':   # V2X doesn't support gsm/gps
                                if board_type[self.boardid]['type'] == 'V2X':
                                    LOG.error("%s isn't a valid option of %s - skip it !!" % \
                                              (key, board_type[self.boardid]['type']))
                                    continue
                            if re.search(r'_enable', key, re.M|re.I):
                                conf_options[key] = int(L[1])
                            else:    
                                if key == 'power_saving_mode':      # validate power_mode
                                    if power_mode.get(L[1]) is None:
                                        LOG.error("%s isn't a valid value of %s - skip it !!" % (L[1], key))
                                        continue
                                    elif not brightness_override:   # adjust brightness default if applicable
                                        conf_options['led_brightness'] = power_mode[L[1]]['led_brightness']
                                elif key == 'openxc_vi_trace_filter_script': # validate filter script
                                    if not os.path.exists(L[1]) or not os.access(L[1], os.X_OK):
                                        LOG.error("%s isn't an executable script for %s - skip it !!" % (L[1], key))
                                        continue
                                elif key == 'led_brightness':       # validate led brightness
                                    brightness = int(L[1])
                                    if brightness < 0 or brightness > 255:
                                        LOG.error("%s isn't a valid value of %s - skip it !!" % (L[1], key))
                                    else:
                                        conf_options[key] = brightness
                                        brightness_override = 1
                                        LOG.debug("new: (%s:%s)" % (key, conf_options[key]))
                                    continue
                                conf_options[key] = L[1]
                            LOG.debug("new: (%s:%s)" % (key, conf_options[key]))
                        else:
                            LOG.error("%s isn't a valid key in %s - skip it !!" % (key, fname))
            except IOError:    
                LOG.error("fail to open %s" % fname)
            else:
                conf.close()
                if not conf_options['openxc_vi_enable']:
                    LOG.info("vi_app is disable")
                    # nothing to passthru
                    for l in passthru_flag.items():
                        (key, val) = l
                        passthru_flag[key] = 0
                else:
                    addr = conf_options['openxc_vi_mac']
                    if addr is not None and addr != 'None':
                        self.addr = addr
                        LOG.info("found %s" % self.addr)
                    # config passthru
                    for l in passthru_flag.items():
                        (key, val) = l
                        passthru_flag[key] = passthru_enable[key]
                self.vi_power_profile()
                vi_auto_upgrade()    # Note: auto upgrade might take awhile

                # handle vi usb-connection if applicable
                if self.usb is None:
                    self.usb = xcmodemUsb()
                    if self.usb.valid() is None:
                        del self.usb
                        self.usb = None
                    else:
                        self.addr = port_mac[self.name]
        return self.addr

    def web_discovery(self, fname):
        # Obtain the config file from predefined URL using scp
        # To maintain the original file, '.web' suffix will be used for
        # the web download file
        LOG.info("Web discovery ... ")

        # Use WiFi if applicable
	if not check_ping() == 0:
            # Use GSM if applicable
            if conf_options['gsm_enable']:
            	if not self.gsm.start():
                    # No need to move on without network connection
                    return None

        # Use sshpass with given psswd for scp
        # Remote cloud server require PEM which is provided in configuration option
        wfname = fname + ".web"
        # Form unique config file name
        if re.search(r'/', conf_options['web_scp_config_url'], re.M|re.I):
            delimiter = '/'
        else:
            delimiter = ':'
        prefix = "%s%s." % (delimiter, socket.gethostname())
        cfname = prefix.join(conf_options['web_scp_config_url'].rsplit(delimiter, 1))
        cmd = "scp -o StrictHostKeyChecking=no -i %s %s@%s %s" % \
                (conf_options['web_scp_pem'], \
                conf_options['web_scp_userid'], \
                cfname, \
                wfname)
        # LOG.debug("issuing '%s'" % cmd)
        if subprocess.call(cmd, shell=True):
            LOG.error("fail to scp %s from %s@%s" % (fname, \
                                                     conf_options['web_scp_userid'], \
                                                     cfname))
            LOG.warn("Please make sure to register your device %s on the web server" % socket.gethostname())
            return None

        # Use WiFi if applicable
	if not check_ping() == 0:
	    # Use GSM if applicable 
            if conf_options['gsm_enable']:
            	# Tear off gsm connection
            	self.gsm.stop()

        # parse the file now
        return self.file_discovery(wfname)


    def gsm_instance(self, force = 0):
        sys.path.append('../modem')                   # GSM is only supported in modem
        import xc_modem_gsm
        if force:    
            if self.gsm is not None:
                LOG.info("Reinstantiate " + self.gsm.name)
                del self.gsm
                self.gsm = None

        # Instantiate gsm module as needed
        if self.gsm is None:
            ppp_tear_off = power_mode[conf_options['power_saving_mode']]['ppp_tear_off']
            self.gsm = xc_modem_gsm.xcModemGsm(sdebug = self.sdebug, debug = self.debug, tear_off = ppp_tear_off)
            if not self.gsm.prep(conf_options['web_scp_apn']):
                LOG.error("There is no network access !!!")
                return False
        return True

    def modem_inquiry(self):
        if (self.modem_ip_addr is None):
          self.modem_ip_addr = conf_options['xcmodem_ip_addr']
          return conf_options['xcmodem_ip_addr']
        else:
           return self.modem_ip_addr


    def modem_available(self, modem_ip_addr):
        LOG.info("Checking if Modem is available %s" % modem_ip_addr)
        cmd = "ping -c 1 " + modem_ip_addr + " > /dev/null 2>&1"
        LOG.info(cmd)
        response = subprocess.call(cmd, shell=True)
        if response == 0:
          LOG.info("Modem responded to ping")
          self.modem_ip_addr = modem_ip_addr 
          self.modem_port = 4567 
          return 1
        else:
          LOG.info("Modem did NOT respond to ping")
          return 0

    def vi_inquiry(self):
        # determine the vi_app address using pre-defined priority scheme
        
        if self.file_discovery(XCMODEM_CONFIG_FILE) is None and conf_options['openxc_vi_enable']:
            if conf_options['web_scp_config_download_enable'] and conf_options['gsm_enable']:
                # Prepare GSM if applicable using correct options
                if not self.gsm_instance():
                    # skip web discovery 
                    if self.auto_discovery() is None:
                        LOG.info("None OPENXC-VI Device Address Assignment!!!")
                elif self.web_discovery(XCMODEM_CONFIG_FILE) is None:
                    if self.auto_discovery() is None:
                        LOG.info("None OPENXC-VI Device Address Assignment!!!")
            elif self.auto_discovery() is None:
                LOG.info("None OPENXC-VI Device Address Assignment!!!")

        # Saving the current config file for reference
        self.conf_save(XCMODEM_CONFIG_FILE + ".cur")

        return self.addr


    def vi_discovery(self):
        LOG.info("Performing inquiry...")

        self.bt_led.blink(1)         # slow blink
        try:
            nearby_devices = bluetooth.discover_devices(duration=10,lookup_names = True)
        except BluetoothError as e:
            LOG.error("BT error %s %s" % (self.name, e))
            return False

        LOG.info("found %d devices" % len(nearby_devices))
        for addr, name in nearby_devices:
            LOG.info("  %s - %s" % (addr, name))
            if (addr is not None and addr == self.addr):
                self.bt_led.off()    # done discovery
                return True
        self.bt_led.off()            # done discovery
        return False



    def vi_pair(self):
        # Work-around for dongle pairing
        # subprocess.call('hciconfig hci0 sspmode disable', shell=True)

        # check if the device has already paired up
        cmd = "bluez-test-device list | grep \"%s\"" % self.addr
        # LOG.debug("issuing: " + cmd)
        if subprocess.call(cmd, shell=True):
            # re-pairing
            LOG.info("pairing %s ..." % self.addr)
            self.bt_led.blink()       # fast blink
            if self.bt5:
                rc = vi_bt5_pair(self.addr, self.debug)
            else:
                cmd = "echo '1234' | bluez-simple-agent hci0 %s 2>&1 1>/dev/null" % self.addr
                # LOG.debug("issuing: " + cmd)
                rc = not subprocess.call(cmd, shell=True)
            self.bt_led.off()         # done pairing
            return rc
        return True


    def modem_connect(self):
        # Modem is acting as Master/Client agent
        LOG.info("trying to connect %s ..." % self.modem_ip_addr)

        attempt = 1
        while (attempt <= MAX_CONNECTION_ATTEMPT):
            # Ensure if the device is paired
            #if self.vi_pair():
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    LOG.info("trying to connect to %s at port %s" % (self.modem_ip_addr, self.modem_port))
                    s.connect((self.modem_ip_addr, self.modem_port))
                except IOError:
                    LOG.warn("Unable to connect to %s " % self.modem_ip_addr)
                    #s.shutdown(socket.SHUT_RDWR)
                    s.close()
                    time.sleep(3)
                else:
                    self.bt_led.blink()
                    LOG.info("Opened modem connection at %s" % self.modem_port)
                    self.socket = s
                    #port_mac[self.name] = self.addr
                    break;
                attempt += 1
                self.bt_led.on()
        return self.socket

    def vi_connect(self):
        # Modem is acting as Master/Client agent
        LOG.info("connect %s ..." % self.addr)

        attempt = 1
        while (attempt <= MAX_CONNECTION_ATTEMPT):
            # Ensure if the device is paired
            if self.vi_pair():
                socket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
                try:
                    socket.connect((self.addr, self.port))
                except IOError:
                    LOG.warn("Unable to connect to %s" % self.addr)
                else:
                    self.bt_led.on()    # dongle connect 
                    LOG.info("Opened bluetooth device at %s" % self.port)
                    self.socket = socket
                    port_mac[self.name] = self.addr
                    break;
            attempt += 1
        return self.socket


#-------------------------------------------------------------------
# Setup environment for backing the log to SD card datalog partition
#-------------------------------------------------------------------
    def trace_sd_backup_prep(self):
        # Prepare mSD mount
        LOG.debug("SD backup prep")
        if int(conf_options['openxc_vi_trace_number_of_backup']) > 0:
            cmd = "fdisk -l %s | grep %s; \
                   if [ $? -eq 0 ]; then \
                     mount | grep %s; \
                     if [ $? -eq 0 ]; then \
                       umount %s; \
                     fi; \
                     mkdir -p %s; \
                     mount /dev/%s %s; \
                   else \
                     exit 1; \
                   fi" % (XCMODEM_DATA_DEVICE, XCMODEM_DATA_PARTITION, \
                          XCMODEM_DATA_MOUNT, \
                          XCMODEM_DATA_MOUNT, \
                          XCMODEM_DATA_MOUNT, \
                          XCMODEM_DATA_PARTITION, XCMODEM_DATA_MOUNT)
            # LOG.debug("issuing '%s'" % cmd)
            if subprocess.call(cmd, shell=True):
                LOG.error("fail to prepare %s - skip SD backup" % XCMODEM_DATA_MOUNT)
                conf_options['openxc_vi_trace_number_of_backup'] = 0    # Turn off SD backup
            else:
                cmd = "df -BK %s | tail -1 | awk '{print $4}' | awk -FK '{print $1}'" % XCMODEM_DATA_MOUNT
                # LOG.debug("issuing '%s'" % cmd)
                self.sd_space = int(subprocess.check_output(cmd, shell=True).split()[0]) * 1024

#-------------------------------------------------------------------
# Backup log to SD card datalog partition
#-------------------------------------------------------------------
    def trace_sd_backup(self, bfname, bfsize, v2x_flag):
        # sd backup file 
        LOG.debug("SD backup")

        # check for space
        fnum = int(conf_options['openxc_vi_trace_number_of_backup'])
        while (fnum > 0) :
            if self.sd_space < bfsize:
                # remove file to make space
                fname = "%s_%s.%s" % (XCMODEM_DATA_TRACE_PREFIX, fnum, XCMODEM_DATA_TRACE_SUFFIX)
                if conf_options['openxc_vi_trace_backup_overwrite_enable']:
                    if os.path.exists(fname):
                        fsize = os.path.getsize(fname)
                        # LOG.debug("removing '%s'" % fname)
                        os.remove(fname)  
                        self.sd_space += fsize
                    fnum -= 1
                else:
                    LOG.info("Skip SD backup due to unsufficent space")
                    return                         # skip if no space left
            else:
                break
        # pump up backup file
        fnum = int(conf_options['openxc_vi_trace_number_of_backup'])
        while (fnum > 0): 
            if v2x_flag:
             fname1 = "%s_%s.%s" % (XCMODEM_DATA_V2X_TRACE_PREFIX, fnum, XCMODEM_DATA_TRACE_SUFFIX)
            else:
             fname1 = "%s_%s.%s" % (XCMODEM_DATA_TRACE_PREFIX, fnum, XCMODEM_DATA_TRACE_SUFFIX)
            fnum -= 1
            if v2x_flag:
             fname2 = "%s_%s.%s" % (XCMODEM_DATA_V2X_TRACE_PREFIX, fnum, XCMODEM_DATA_TRACE_SUFFIX)
            else:
             fname2 = "%s_%s.%s" % (XCMODEM_DATA_TRACE_PREFIX, fnum, XCMODEM_DATA_TRACE_SUFFIX)
            if os.path.exists(fname2):
                if os.path.exists(fname1):         # gain space
                     self.sd_space += os.path.getsize(fname1)
                # LOG.debug("rename '%s to %s' " % (fname2, fname1))
                os.rename(fname2, fname1)
        # backup recent raw file
        if v2x_flag:
          fname = "%s_1.%s" % (XCMODEM_DATA_V2X_TRACE_PREFIX, XCMODEM_DATA_TRACE_SUFFIX)
        else:
          fname = "%s_1.%s" % (XCMODEM_DATA_TRACE_PREFIX, XCMODEM_DATA_TRACE_SUFFIX)
        cmd = "cp -p %s %s" % (bfname, fname)
        #LOG.debug("issuing '%s' " % cmd)
        if subprocess.call(cmd, shell=True):
            LOG.error("fail to backup %s" % fname)
        else:
            self.sd_space -= bfsize

#-------------------------------------------------------------------
# Control for capturing VI trace log
#-------------------------------------------------------------------

    def trace_start(self, interval, rfname, bfname):
        LOG.debug("Recording start: %s" % rfname)
        # set up new trace
        self.trace_raw_lock.acquire()
        self.fp = open(rfname, "w+")
        self.trace_raw_lock.release()
        self.trace_enable = 1
        time.sleep(interval)
        self.trace_enable = 0
        self.trace_raw_lock.acquire()
        self.fp.close()
        if (os.path.isfile(rfname)):
         os.rename(rfname, bfname)
         bfsize = os.path.getsize(bfname)
        if (os.path.isfile(bfname)):
         LOG.debug("Recording stop (size: %s) : %s" % (bfsize, rfname))
        else:
         LOG.debug("VI Recording failed") 

        if int(conf_options['openxc_vi_trace_number_of_backup']) > 0:   # if SD backup is needed
            self.trace_sd_backup(bfname, bfsize,0)
        self.trace_raw_lock.release()

#-------------------------------------------------------------------
# Control for capturing V2X/RSU trace log
#-------------------------------------------------------------------
    def v2x_trace_start(self, interval, rfname, bfname):
        LOG.debug("Recording start: %s" % rfname)
        # set up new trace
        self.v2x_trace_raw_lock.acquire()
        self.v2x_fp = open(rfname, "w+")
        self.v2x_trace_raw_lock.release()
        self.v2x_trace_enable = 1
        time.sleep(interval)
        self.v2x_trace_enable = 0
        self.v2x_trace_raw_lock.acquire()
        self.v2x_fp.close()
        if (os.path.isfile(rfname)):
            os.rename(rfname, bfname)
        bfsize = os.path.getsize(bfname)
        if (os.path.isfile(bfname)):
         LOG.debug("Recording stop (size: %s) : %s" % (bfsize, rfname))
        else:
         LOG.debug("v2x Recording failed") 
        if int(conf_options['openxc_vi_trace_number_of_backup']) > 0:   # if SD backup is needed
            self.trace_sd_backup(bfname, bfsize,1)
        self.v2x_trace_raw_lock.release()


    def trace_prep(self, bfname, fname):
        # make bk file readable so we can present it over network later on
        #LOG.debug("Recording conversion")
        # handle filtering script if applicable
        if conf_options['openxc_vi_trace_filter_script'] is None or \
           conf_options['openxc_vi_trace_filter_script'] == 'None':
            filter = ""
        else:
            filter = "| %s" % conf_options['openxc_vi_trace_filter_script']
        cmd = "sed -e 's/\\x0/\\r\\n/g' %s | sed -n -e '/{/ { /}/p }' %s > %s" % (bfname, filter, fname)
        truncate_size = int(conf_options['openxc_vi_trace_truncate_size'])
        self.trace_lock.acquire()
        # LOG.debug("issuing '%s'" % cmd)
        if subprocess.call(cmd, shell=True):
            LOG.error("fail to convert %s" % fname)
        elif truncate_size:
            LOG.debug("Truncate %s to %s bytes" % (fname, truncate_size))
            fp = open(fname, "rw+")
            fp.truncate(truncate_size)
            fp.close()
        self.trace_lock.release()


    def web_upload(self, bfname, fname):
        if not os.path.exists(bfname):
            LOG.debug("No trace yet to be uploaded") 
            return

        # Prep the trace file
        self.trace_prep(bfname, fname)

        # Use WiFi if applicable 
        if not check_ping() == 0:
            if (boardid_inquiry() > 1):
              #LOG.info("No connection to cloud found!! Skipping upload")
              return 
            # Use GSM if applicable
            if conf_options['gsm_enable']:
            	# Create gsm instance as needed
            	if not self.gsm_instance():
                    return
            	if not self.gsm.start():
                    # No need to move on without network 
                    if modem_state[self.gsm.name] == app_state.LOST:
                        # Create new gsm instance to re-establishing modem connection
                        if not self.gsm_instance(force = 1):
                            return
                        if not self.gsm.start():
                            return
                    else:
                    	return

        # OXM-93: Need timeout to terminate scp process in case something goes wrong
        timeout = (float(conf_options['openxc_vi_trace_snapshot_duration']) * UPLOAD_TIMEOUT_FACTOR) + UPLOAD_OVERHEAD_TIME

        # Use sshpass with given psswd for scp
        # Remote cloud server require PEM which is provided in configuration option
        if conf_options['web_scp_target_overwrite_enable']:
            timestamp = ""
        else:
            timestamp = ".%s" % datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")
        if re.search(r'/', conf_options['web_scp_vi_target_url'], re.M|re.I):
            delimiter = '/'
        else:
            delimiter = ':'
        prefix = "%s%s%s." % (delimiter, socket.gethostname(), timestamp)
        target = prefix.join(conf_options['web_scp_vi_target_url'].rsplit(delimiter, 1))
        cmd = "timeout %s scp -o StrictHostKeyChecking=no -i %s %s %s@%s" % \
                (int(timeout), \
                conf_options['web_scp_pem'], \
                fname, \
                conf_options['web_scp_userid'], \
                target)
        #LOG.debug("VI_WEB_UPLOAD - issuing '%s'" % cmd)
        self.trace_lock.acquire()
        rc = subprocess.call(cmd, shell=True)
        if rc:
            if rc == TIMEOUT_RC:
                msg = "Timeout (%ds)" % int(timeout)
                #modem_state[self.gsm.name] = app_state.LOST
                modem_state[self.name] = app_state.LOST
            else:
                msg = "Fail"
            LOG.error("%s to scp upload %s to %s@%s" % (msg, fname, \
                                                        conf_options['web_scp_userid'], \
                                                        target))
        self.trace_lock.release()

	# Use WiFi if applicable
        if not check_ping() == 0:
	    # Use GSM if applicable 
            if conf_options['gsm_enable']:
            	# Tear off gsm connection
            	self.gsm.stop()
#===================================================================
    def web_v2x_upload(self, bfname, fname):
        LOG.debug("******>>>> Start uploading trace to Web")

        if not os.path.exists(bfname):
            #LOG.debug("No trace yet to be uploaded")
            return

        # Prep the trace file
        self.trace_prep(bfname, fname)

        # Use WiFi if applicable
        if not check_ping() == 0:
            if (boardid_inquiry() > 1):
              #LOG.info("No connection to cloud found!! Skipping upload")
              return
            # Use GSM if applicable
            if conf_options['gsm_enable']:
                # Create gsm instance as needed
                if not self.gsm_instance():
                    return
                if not self.gsm.start():
                    # No need to move on without network
                    if modem_state[self.gsm.name] == app_state.LOST:
                        # Create new gsm instance to re-establishing modem connection
                        if not self.gsm_instance(force = 1):
                            return
                        if not self.gsm.start():
                            return
                    else:
                        return
        # OXM-93: Need timeout to terminate scp process in case something goes wrong
        timeout = (float(conf_options['openxc_v2x_trace_snapshot_duration']) * UPLOAD_TIMEOUT_FACTOR) + UPLOAD_OVERHEAD_TIME

        # Use sshpass with given psswd for scp
        # Remote cloud server require PEM which is provided in configuration option
        if conf_options['web_scp_target_overwrite_enable']:
            timestamp = ""
        else:
            timestamp = ".%s" % datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")
        if re.search(r'/', conf_options['web_scp_xcV2Xrsu_target_url'], re.M|re.I):
            delimiter = '/'
        else:
            delimiter = ':'
        prefix = "%s%s%s." % (delimiter, socket.gethostname(), timestamp)
        target = prefix.join(conf_options['web_scp_xcV2Xrsu_target_url'].rsplit(delimiter, 1))
        cmd = "timeout %s scp -o StrictHostKeyChecking=no -i %s %s %s@%s" % \
                (int(timeout), \
                conf_options['web_scp_pem'], \
                fname, \
                conf_options['web_scp_userid'], \
                target)
        #LOG.debug("XCV2X_WEB_UPLOAD - issuing '%s'" % cmd)
        self.trace_lock.acquire()
        rc = subprocess.call(cmd, shell=True)
        if rc:
            if rc == TIMEOUT_RC:
                msg = "Timeout (%ds)" % int(timeout)
                #modem_state[self.gsm.name] = app_state.LOST
                modem_state[self.name] = app_state.LOST
            else:
                msg = "Fail"
            LOG.error("%s to scp upload %s to %s@%s" % (msg, fname, \
                                                        conf_options['web_scp_userid'], \
                                                        target))
        self.trace_lock.release()

        # Use WiFi if applicable
        if not check_ping() == 0:
            # Use GSM if applicable
            if conf_options['gsm_enable']:
                # Tear off gsm connection
                self.gsm.stop()


#===================================================================

    def conf_save(self, fname):
        LOG.debug("Configuration saving")
        fp = open(fname, "w+")
        for l in conf_options.items():
            (key, val) = l
            fp.write("%s %s\r\n" % (key, val))
        fp.close()


    def vi_exit(self):
        # terminate passthru
        for l in passthru_flag.items():
            (key, val) = l
            passthru_flag[key] = 0
        # clean up function after OPERATION state
        if self.usb:
            del self.usb
            self.usb = None
            self.addr = None
        if self.socket:
            self.socket.shutdown(socket.SHUT_RDWR)
            self.socket.close()
            self.socket = None
        if self.stop_trace:
            self.stop_trace.set()
        if self.stop_web_upload:
            LOG.debug("Web uploading end")
            self.stop_web_upload.set()
        if self.stop_v2x_web_upload:
            LOG.debug("Web v2x uploading end")
            self.stop_v2x_web_upload.set()
        if self.stop_monitor:
            LOG.debug("Monitor end")
            self.stop_monitor.set()
        if self.stop_button_monitor:
            LOG.debug("Reset Button Monitor end")
            self.stop_button_monitor.set()
        if self.fp:
            self.trace_raw_lock.acquire()
            self.fp.close()
            self.trace_raw_lock.release()
        if self.v2x_fp:
            self.trace_raw_lock.acquire()
            self.v2x_fp.close()
            self.trace_raw_lock.release()
        # flush the queues
        while not self.inQ.empty():
            self.inQ.get()
        while not self.outQ.empty():
            self.outQ.get()
        # Wait for all threads to complete
        for t in self.threads:
            t.join()
        # reset exit_flag
        exit_flag[self.name] = 0
        LOG.debug("Ending " + self.name)


    def vi_timestamp(self, data):
        # add timestamp    
        rstr = ',\"timestamp\":%6f}' % time.time()
        new = string.replace(data, '}', rstr)
        return new


    def led_brightness(self, level):
        # LED Brightness via MAX5432 
        I2C_ADDRESS = 0x28
        REG_VREG = 0x11
        status = self.led_cntl.write_byte_data(I2C_ADDRESS, REG_VREG, level)


    def battery_charger_check(self):
        # charger access using Ti bq24196
        I2C_ADDRESS = 0x6b
        REG_STATUS = 0x08
        REG_FAULT = 0x09
        CHARGE_MASK = 0x30
        state_list = { 0x00: charge_state.NOT_CHARGE,
                       0x10: charge_state.PRE_CHARGE,
                       0x20: charge_state.FAST_CHARGE,
                       0x30: charge_state.CHARGE_DONE }

        # For fault decoding: {value: (mask, desc)}
        fault_list = { 0x80: ( 0x80, 'WDOG FAULT'),     # bit7
                       0x40: ( 0x40, 'BOOST FAULT'),    # bit6
                       0x30: ( 0x30, 'SAFETY FAULT'),   # bit[5:4]
                       0x20: ( 0x30, 'THERMAL FAULT'),  # bit[5:4]
                       0x10: ( 0x30, 'INPUT FAULT'),    # bit[5:4]
                       0x08: ( 0x08, 'BATOVP FAULT'),   # bit[3]
                       0x06: ( 0x07, 'HOT FAULT'),      # bit[2:1]
                       0x05: ( 0x07, 'COLD FAULT') }    # bit[2:1]

        status = self.charger.read_byte_data(I2C_ADDRESS,REG_STATUS)
        fault = self.charger.read_byte_data(I2C_ADDRESS,REG_FAULT)
        if self.debug:
            LOG.debug("status = x%X fault = x%X" % (status, fault))

        state = state_list[status & CHARGE_MASK]
        if modem_state['charger'] != state:
            modem_state['charger'] = state

        if fault != self.charger_fault:
            LOG.info("Charger Fault Register: x%X -> x%X" % (self.charger_fault, fault))
            self.charger_fault = fault
            # fault decoding
            for val in fault_list.keys():
                mask, desc = fault_list[val]
                if (fault & mask) == val:
                    LOG.info("   Fault: %s" % desc)

        return (modem_state['charger'] == charge_state.PRE_CHARGE \
             or modem_state['charger'] == charge_state.FAST_CHARGE)


    def battery_check(self):
        # Threshold value provided by HW team
        GREEN_THRESHOLD = 3.65
        RED_THRESHOLD = 3.55
        ADC_ADJUSTMENT = 0.04         # ~1% of 3.3

        dev = "/sys/devices/ahb/ahb:apb/f8018000.adc/iio:device0"
        cmd = "cat %s/in_voltage3_raw" % dev
        raw = float(subprocess.check_output(cmd, shell=True).split()[0])
        volt = (raw / 2048 * 3.3) +  ADC_ADJUSTMENT
        if self.debug:
            LOG.debug("raw = %f voltage = %f" % (raw, volt))
        charging = self.battery_charger_check() 
        if volt >= GREEN_THRESHOLD:   # green
            self.bat_led_red.off()
            if charging:
                self.bat_led_grn.blink()
            else:
                self.bat_led_grn.on()
        elif volt >= RED_THRESHOLD:   # amber
            if charging:
                self.bat_led_grn.blink()
                self.bat_led_red.blink()
            else:
                self.bat_led_grn.on()
                self.bat_led_red.on()
        else:                         # red
            self.bat_led_grn.off()
            if charging:
                self.bat_led_red.blink()
            else:
                self.bat_led_red.on()


    def vi_monitor(self):
        # enviornment monitor task
        self.battery_check()
        pass


    def vi_reset_button_monitor(self):
        # obtain irq count
        prev_irq_cnt = self.button_irq_cnt
        cmd = "cat /proc/interrupts | grep PB_RST | awk '{print $2'}"
        self.button_irq_cnt = int(subprocess.check_output(cmd, shell=True).strip())
        if self.debug:
            LOG.debug("Reset button monitor: irq=%s %s" % (prev_irq_cnt, self.button_irq_cnt))
        if (self.button_irq_cnt == (prev_irq_cnt + 1)):    # reset button was held 
            # Perform Firmware Reset 
            xc_led.all_leds(3)                    # all leds slow blink
            LOG.info("Firmware Reset Button Activated !!!")
            ver, fname = subprocess.check_output("cat ../backup/factory/upgrade.ver", shell=True).split()
            LOG.info("Firmware Reset to %s ..." % ver)
            LOG.info("System will be reset after Firmware Reset ...")
            cmd = "rm -fr ../backup/current; cp -pr ../backup/factory ../backup/current; \
                   cp -f ../backup/current/%s /tmp; \
                   cd /tmp; tar xvf %s; ./xc-upgrade.sh" % (fname, fname)
            # LOG.debug("issuing: " + cmd)
            if subprocess.call(cmd, shell=True):
                LOG.debug("firmware reset fail")


    def vi_power_profile(self):
        # power-saving-mode profile
        mode = conf_options['power_saving_mode']
        LOG.info("Power mode configuration: " + mode)
        self.led_brightness(conf_options['led_brightness'])


    def vi_main(self):
        attempt = 1
        conf_options['openxc_modem_mac'] = self.modem_mac_inquiry()

        # OXM-72: Rarely if BT frame errors occur at discovery time, VI dongle
        #   stucks at connection state while bluez is too messed up even to let
        #   us tearing down the connection. To work-around, we'd restart bluetooth
        #   and bringup TI device accordingly.  
        stuck_state = vi_state.ADDR_INQUIRY
        self.board_id = boardid_inquiry()
        self.config_mode = boardmode_inquiry()
        stuck_cnt = 0
        LOG.info("**********>    Entering vi_main  <*************")
        LOG.info("Board ID     = %s"  % self.board_id)
        LOG.info("Config mode  = %s " % self.config_mode)
        LOG.info("***********************************************")
        
        #if ((boardid_inquiry() == 2) and (self.config_mode == 4) or (self.config_mode ==5)):
        if ((self.board_id  == 2) and (self.config_mode == 3)): # i.e. execute following code for v2x in mode 3 only
         LOG.info(">>>>>>>>> Checking for modem <<<<<<<<<<<<")
         while (attempt <= MAX_DISCOVERY_ATTEMPT):
            modem_state[self.name] = vi_state.MODEM_DISCOVERY
            if self.modem_inquiry() is not None:
              modem_state[self.name] = vi_state.MODEM_ADDR_FOUND
              LOG.info(" Modem Address found")
              if (self.modem_available(conf_options['xcmodem_ip_addr'])):
                modem_state[self.name] = vi_state.MODEM_UP
                LOG.info(" Modem is UP")
                if(self.modem_connect()):
                  modem_state[self.name] = vi_state.MODEM_CONNECTED
                  LOG.info("setting vi_conn_type to MODEM")
                  self.conn_type = 'MODEM'
                  LOG.info(" Modem is connected")
                  break
            if stuck_state != modem_state[self.name]:
                stuck_state = modem_state[self.name]
                stuck_cnt = 1
            else:
                stuck_cnt += 1

            LOG.info("MODEM DISOVERY - vi_app.state = %s after %d attempt" % (modem_state[self.name], attempt))
            attempt += 1
         if (modem_state[self.name] != vi_state.MODEM_CONNECTED):
                LOG.info("Modem not connected ....")
                return 0
   
        if (conf_options['openxc_vi_enable']):
         attempt =1
         LOG.info("Enering VI discovery")
         while (attempt <= MAX_DISCOVERY_ATTEMPT):
                    self.bt_led.off()                       # hasn't yet connection
                    conf_options['openxc_vi_mac'] = 'None'  # restore default value
                    self.addr = None
                    modem_state[self.name] = vi_state.ADDR_INQUIRY
                    if self.vi_inquiry() is not None:
                        if self.usb is not None:    # bypass BT discovery
                            modem_state[self.name] = vi_state.CONNECTED
                            break
                        modem_state[self.name] = vi_state.ADDR_ASSIGNED
                        if  self.discovery_once or self.vi_discovery():
                            modem_state[self.name] = vi_state.DISCOVERED
                            if self.vi_connect() is not None:
                                modem_state[self.name] = vi_state.CONNECTED
                                break
                    elif not conf_options['openxc_vi_enable']:
                        modem_state[self.name] = vi_state.DISABLE
                        break;

                    if stuck_state != modem_state[self.name]:
                        stuck_state = modem_state[self.name]
                        stuck_cnt = 1
                    else:
                        stuck_cnt += 1

                    LOG.info("vi_app.state = %s after %d attempt" % (modem_state[self.name], attempt))
                    attempt += 1
         if (modem_state[self.name] != vi_state.CONNECTED):
                    LOG.info("VI not connected ....")
                    #return 0

	LOG.info("XC_VI.PY main IF is %s" %(modem_state[self.name] == vi_state.CONNECTED) or (modem_state[self.name] == vi_state.MODEM_CONNECTED))


        if ((conf_options['openxc_vi_enable']==0) and (boardmode_inquiry()==3)) or (modem_state[self.name] == vi_state.CONNECTED) or (modem_state[self.name] == vi_state.MODEM_CONNECTED):
            #-------------------------------------------------------
            # create usb threads if VI is connected through usb
            #-------------------------------------------------------
            if self.usb is not None:
                thread1 = usbRecvThread("%s-Recv" % self.name, self.usb, self.inQ, self.name)
                thread2 = usbSendThread("%s-Send" % self.name, self.usb, self.outQ, self.name)
            if (conf_options['openxc_vi_enable']): # connect through Bluotooth socket
                # OXM-65 - Use Socket Recv timeout to indicate xfer stop after BT Frame failure
   	            LOG.info("TRYING TO CONNECT VIA BT in xc_vi.py")
                thread1 = sockRecvThread("%s-Recv" % self.name, self.socket, self.inQ, self.name, sflag = 1)
				thread2 = sockSendThread("%s-Send" % self.name, self.socket, self.outQ, self.name)
				
				# start thread
                thread1.start()
				thread2.start()

                self.threads.append(thread1)
				self.threads.append(thread2)

            #--------------------------------------------------
            # prepare SD card back up is more than one backup is desired
            #--------------------------------------------------
            if conf_options['openxc_vi_trace_number_of_backup']:
                self.trace_sd_backup_prep()

            if (conf_options['openxc_vi_enable']):
              #---------------------------------------------------
              # invoke stop_xxx.set() to stop the task if needed
              # start trace task asap
              #---------------------------------------------------
              LOG.info("*****************************")
              LOG.info("Starting VI Trace Log deamon")
              LOG.info("*****************************")
              thread3, self.stop_trace = loop_timer(float(conf_options['openxc_vi_trace_idle_duration']), \
                                           self.trace_start, \
                                           float(conf_options['openxc_vi_trace_snapshot_duration']), \
                                           XCMODEM_TRACE_RAW_FILE, XCMODEM_TRACE_RAW_BK_FILE)
              self.threads.append(thread3)

            #---------------------------------------------------
            # start v2x trace 
            #---------------------------------------------------
            if (self.boardid == 1) and (self.config_mode == 3):
             LOG.info("*****************************")
             LOG.info("Starting V2X Trace Log deamon")
             LOG.info("*****************************")
             thread7, self.stop_v2x_trace = loop_timer(float(conf_options['openxc_v2x_trace_idle_duration']), \
                                         self.v2x_trace_start, \
                                         float(conf_options['openxc_v2x_trace_snapshot_duration']), \
                                         XCMODEM_V2X_TRACE_RAW_FILE, XCMODEM_V2X_TRACE_RAW_BK_FILE)
             self.threads.append(thread7)

            #---------------------------------------------------
            # for web upload, we use the stable back up file
            #---------------------------------------------------
            if conf_options['web_scp_vi_trace_upload_enable']:
              #if (not ((board_id == 2) and ((self.config_mode == 4) or (self.config_mode == 5)))):
              if (not ((self.board_id == 2) and (self.config_mode == 3))):
                if (conf_options['openxc_vi_enable']):
		  thread4, self.stop_web_upload = loop_timer(float(conf_options['web_scp_vi_trace_upload_interval']), \
                                                    self.web_upload, \
                                                    XCMODEM_TRACE_RAW_BK_FILE, XCMODEM_TRACE_FILE) 
                  self.threads.append(thread4)
                thread4_1, self.stop_web_v2x_upload = loop_timer(float(conf_options['web_scp_vi_trace_upload_interval']), \
                                                  self.web_v2x_upload, \
                                                 #XCMODEM_TRACE_RAW_BK_FILE, XCMODEM_TRACE_FILE) 
                                                  XCMODEM_V2X_TRACE_RAW_BK_FILE, XCMODEM_V2X_TRACE_FILE)
                self.threads.append(thread4_1)

            #-----------------------------------------------------
            # start monitor task
            #-----------------------------------------------------
            monitor_interval = float(power_mode[conf_options['power_saving_mode']]['monitor_interval'])
            thread5, self.stop_monitor = loop_timer(monitor_interval, self.vi_monitor) 
            self.threads.append(thread5)

            # FW Reset button monitor
            if conf_options['fw_factory_reset_enable']:
                thread6, self.stop_button_monitor = loop_timer(FIRMWARE_RESET_BUTTON_MONITOR_INTERVAL, self.vi_reset_button_monitor) 
                self.threads.append(thread6)

            modem_state[self.name] = vi_state.OPERATION
        elif modem_state[self.name] != vi_state.DISABLE:
            exit_flag[self.name] = 1
            if stuck_cnt >= MAX_DISCOVERY_ATTEMPT \
                and (stuck_state == vi_state.ADDR_ASSIGNED \
                  or stuck_state == vi_state.DISCOVERED):
                LOG.debug("VI/MODEM probably stucks! Work-around to re-start bluetooth")
                if self.bt5:    
                    LOG.debug("Bluetooth 5 restart doesn't work! Please restart your test !!")
                    exit_flag['all_app'] = 1
                else:
                    modem_state[self.name] = vi_state.RESTART
                    vi_bt_restart(self.name)
            
        LOG.info("vi_app.state = %s" % modem_state[self.name])
        return (modem_state[self.name] == vi_state.OPERATION)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', help='Verbosity Level (0..2)')
    args = parser.parse_args()

    if args.v is None:
        level = 0
    else:
        level = int(args.v)

    pairing_registration()
    vi_cleanup()
    vi_dev = xcModemVi(port_dict['vi_app']['port'], vi_in_queue, vi_out_queue, \
                       sdebug = (level>1), debug = (level>0))
    attempt = 1

    while True:
        if (vi_dev.vi_main()):
            while not exit_flag['vi_app']:
                while not vi_in_queue.empty():
                    data = vi_dev.inQ.get()
                    # print("rec [%s]" % data)
                    new = vi_dev.vi_timestamp(data)    
                    # print("new [%s]" % new)
                    # simply dump into a file 
                    vi_dev.trace_raw_lock.acquire()
                    if vi_dev.fp and vi_dev.trace_enable:
                        vi_dev.fp.write(new)
                    vi_dev.trace_raw_lock.release()
                msleep(1)
            modem_state['vi_app'] = vi_state.LOST
            vi_dev.lost_cnt += 1
            LOG.info("vi_app state %s %d time" % (modem_state['vi_app'], vi_dev.lost_cnt))
            vi_dev.vi_exit()

        if exit_flag['all_app']:
            LOG.debug("Ending all_app")
            break;
        time.sleep(float(conf_options['openxc_vi_discovery_interval']))
        attempt += 1
        if (attempt > MAX_BRING_UP_ATTEMPT):
            LOG.debug("vi_app max out %d attempts in xc_vi.py" % MAX_BRING_UP_ATTEMPT)
            break;
            


