MODEM_SSD_TRACE_PREFIX = '/mnt/ssd/trace_raw'

# $Rev:: 265           $
# $Author:: mlgantra   $
# $Date:: 2015-04-20 1#$
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
from smbus import SMBus
import select
import errno
import commands

try: 
    import bluetooth
except ImportError:
    LOG.debug("pybluez library not installed, can't use bluetooth interface")
    bluetooth = None

from xc_common import *
import xc_led
import xc_ver
from ota_upgrade import *

XCMODEM_CONFIG_FILE = 'xc.conf'
XCMODEM_XCV2XRSU_TRACE_RAW_FILE = 'xcV2Xrsu_trace_raw.json'
XCMODEM_XCV2XRSU_TRACE_RAW_BK_FILE = 'xcV2Xrsu_trace_raw_bk.json'
XCMODEM_XCV2XRSU_TRACE_FILE = 'xcV2Xrsu_trace.json'

XCMODEM_SSD_MOUNT = '/mnt/ssd'
XCMODEM_SSD_DEVICE = '/dev/mmcblk0'
XCMODEM_SSD_PARTITION = 'mmcblk0p2'
XCMODEM_SSD_TRACE_PREFIX = '/mnt/ssd/trace_raw'

XCMODEM_SSD_V2X_TRACE_PREFIX = '/mnt/ssd/v2x_trace_raw'
XCMODEM_SSD_TRACE_SUFFIX = 'json'


UPLOAD_TIMEOUT_FACTOR = 0.05            # in=7K/s out=140K/s
UPLOAD_OVERHEAD_TIME  = 30              # 30s
TIMEOUT_RC = 124

#-----------------------------------------------------------------
# restart function. used when cohda inteface is not found
# an attempt will be made to restart it
#-----------------------------------------------------------------
def cohda_cw_llc_restart(name):
    # restart bluetooth 
    LOG.debug("Re-starting cw-llc ...")

    exit_flag['chd_restart'] = 1
    # call the cohda restart command
    cmd = "/root/OpenXCAccessory/startup/cw_llc_restart.sh"
    # LOG.debug("issuing: " + cmd)
    try:
        subprocess.call(cmd, shell=True)
    except Exceptions as e:
        LOG.debug("%s %s" % (name, e))
        pass
    else:
       exit_flag['chd_restart'] = 0

#-----------------------------------------------------------------
# Class/Thread definition for the RSU interface 
# it is used by V2X and RSU units where the send and revc ports
# are reversed
#-----------------------------------------------------------------
class xcV2Xrsu:
    def __init__(self, name, send_port, recv_port, inQ, outQ, sdebug = 0, debug = 0):
        #self.port = port
        self.addr = None
        self.socket = None
        self.discovery_once = False
        self.inQ = inQ
        self.outQ = outQ
        self.fp = None
        self.name = name 
        self.trace_enable = 0
        self.stop_web_upload = None
        self.stop_trace = None
        self.stop_monitor = None
        self.trace_lock = threading.Lock()
        self.trace_raw_lock = threading.Lock()
        self.threads = []
        self.lost_cnt = 0
        self.sdebug = sdebug
        self.debug = debug
        self.boardid = boardid_inquiry(1)
        self.modem_ip_addr = None
        self.modem_port = None
        self.send_socket = None
        self.recv_socket = None
        self.send_port = send_port
        self.recv_port = recv_port
        self.conn_type = None
        self.config_mode = None
        # LEDs instances
        pathid = self.boardid > 0
        self.bt_led = xc_led.xcModemLed('bt_led', led_path['bt'][pathid])

	self.wifi_led = xc_led.xcModemLed('wifi_led', led_path['gps'][pathid])

	self.dsrc_led = xc_led.xcModemLed('dsrc_led', led_path['wifi'][pathid])
        self.bat_led_grn = xc_led.xcModemLed('bat_led_grn', led_path['bat_grn'][pathid])
        self.bat_led_red = xc_led.xcModemLed('bat_led_red', led_path['bat_red'][pathid])
        self.bt_led.on()
        modem_state[self.name] = xcV2Xrsu_state.IDLE
        self.charger = SMBus(0)   # open Linux device /dev/ic2-0
        self.led_cntl = SMBus(2)  # open Linux device /dev/ic2-2
        self.charger_fault = 0
        self.battery_check()


#--------------------------------------------------------------------------
# function to time stamp RSU data 
#--------------------------------------------------------------------------
    def xcV2Xrsu_timestamp(self, data):
        # add timestamp
        rstr = ',\"timestamp\":%6f}' % time.time()
        new = string.replace(data, '}', rstr)
        return new

#--------------------------------------------------------------------------
# I think the battery functionality should be carved out as separate object
#--------------------------------------------------------------------------
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
            #LOG.info("charger state %s" % modem_state['charger'])

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

    def xcV2Xrsu_monitor(self):
        # enviornment monitor task
        self.battery_check()
        pass

#-----------------------------------------------------------------------------
    def file_discovery(self, fname):
        # Return address from existing configuration file

        LOG.info("Static discovery ...")
        brightness_override = 0
        if os.path.exists(fname):
            # setup default based on modem/v2x board
            for key in ['gsm_enable', 'gps_enable']:
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
                addr = conf_options['openxc_vi_mac']
                if addr is not None and addr != 'None':
                    self.addr = addr
                    LOG.info("found %s" % self.addr)
                self.vi_power_profile()
        return self.addr

    def web_server_available(self, web_scp_url):
        LOG.info("Checking if web server is available %s" % web_scp_url)
        cmd = "ping -c 1 " + web_scp_url + " > /dev/null"
        LOG.info(cmd)
        response = subprocess.call(cmd, shell=True)
        if response == 0:
          return 1
        else:
          return 0


    def web_discovery(self, fname):
        # Obtain the config file from predefined URL using scp
        # To maintain the original file, '.web' suffix will be used for
        # the web download file
        LOG.info("Web discovery ... ")

        #-------------------------------------------------
        # add the code for checking if WiFi is available
        # and/or web site is accessible
        # ping the server
        #------------------------------------------------

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

        # parse the file now
        return self.file_discovery(wfname)
#-----------------------------------------------------------------------
# Get MAC address for COHDA interface 
#-----------------------------------------------------------------------
    def get_chd_mac_addr(self):
        #get the ip address of cw-llc interface
        intf = 'cw-llc'
        #cmd_op = commands.getoutput("ifconfig | grep " + intf ).split()
        cmd_op = commands.getoutput("ifconfig | grep " + intf )
        if (cmd_op.find('HWaddr')) != -1:
          tokens = cmd_op.split()
          mac_addr = tokens[tokens.index('HWaddr') + 1]
          return mac_addr

        else:
          return None

#-----------------------------------------------------------------------
# Get ip address for COHDA interface 
#-----------------------------------------------------------------------
    def get_chd_ip_addr(self):
        #get the ip address of cw-llc interface
        intf = 'cw-llc'
        cmd_op = commands.getoutput("ip address show dev " + intf)
        if (cmd_op.find('inet')) != -1:
           intf_ip = cmd_op.split()
           intf_ip = intf_ip[intf_ip.index('inet') + 1].split('/')[0]
           return intf_ip
        else:
	    return None

#-----------------------------------------------------------------------
# Check if Cohda module ip address has been specified in the config file
#-----------------------------------------------------------------------
    def modem_inquiry(self):
        self.modem_ip_addr = self.get_chd_ip_addr()
        if (not self.modem_ip_addr is None):
           LOG.info("802.11p Modem ip Address = %s" % self.modem_ip_addr)
        else:
           LOG.info("Cohda module not found")
        return self.modem_ip_addr

#-----------------------------------------------------------------------
# Check if 801.11p interface is up in ifconfig 
#-----------------------------------------------------------------------
#    def modem_available(self, chd_modem_ip_addr):
    def modem_available(self):
         intf = 'cw-llc'
         intf_ip = commands.getoutput("ip address show dev " + intf).split()
         intf_ip = intf_ip[intf_ip.index('inet') + 1].split('/')[0]

         intf_ip = self.get_chd_ip_addr()
      
        
         if (not intf_ip is None):
	   # JMA add dsrc_led
	   self.dsrc_led.on()
           return 1
         else: 
           return 0

#-----------------------------------------------------------------------
# Connecto 801.110 modem and open UDP connections for Tx and Rx
#-----------------------------------------------------------------------
    def modem_connect(self):
        # Modem is acting as Master/Client agent
        LOG.info("trying to connect %s ..." % self.modem_ip_addr)
        s = None
        r = None

        attempt = 1
        while (attempt <= MAX_CONNECTION_ATTEMPT):
                try:
	            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # send  socket
                    s.bind((self.modem_ip_addr, 0))
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                   
                except socket.error, msg:
                    LOG.warn("Unable to create a UDP socket to %s error %s"  % (self.modem_ip_addr, msg))
                else:
                    #LOG.info("Opened modem  UDP connection for RSU for sending"  % self.send_port)
                    LOG.info("Opened modem  UDP connection for RSU for sending")
                    self.send_socket = s
		    # JMA add dsrc_led
		    self.dsrc_led.blink()
                    break;
                attempt += 1
        attempt = 1
        while (attempt <= MAX_CONNECTION_ATTEMPT):
                try:
	            r = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # send  socket
                    r.bind(('', self.recv_port))
                   
		    # JMA add dsrc_led
                except socket.error, msg:
                    LOG.warn("Unable to create a UDP socket to %s error %s"  % (self.modem_ip_addr, msg))
		    self.dsrc_led.off()
                else:
                    #LOG.info("Opened modem  UDP connection for RSU at recv %s" % self.recv_port)
                    LOG.info("Opened modem  UDP connection for RSU for receive" )
                    self.recv_socket = r
		    self.dsrc_led.blink()
                    break;
                attempt += 1
        if (self.send_socket is None) or ( self.recv_socket is None):
         return False 
        else:
         return True 


    def xcV2Xrsu_inquiry(self):
        # determine the vi_app address using pre-defined priority scheme
#==========
# update this code to make cohda related inquiry
#=========        
        gsm_setup = 1
        if self.file_discovery(XCMODEM_CONFIG_FILE) is None:
            if conf_options['web_scp_config_download_enable'] and conf_options['gsm_enable']:
                # Prepare GSM if applicable using correct options
                gsm_setup = 0
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

#==========================================
# not needed it for RSU 
#==========================================        
    # def vi_discovery(self):
    #     LOG.info("Performing inquiry...")
    #
    #     self.bt_led.blink()
    #     nearby_devices = bluetooth.discover_devices(duration=10,lookup_names = True)
    #     LOG.info("found %d devices" % len(nearby_devices))
    #     for addr, name in nearby_devices:
    #         LOG.info("  %s - %s" % (addr, name))
    #         if (addr is not None and addr == self.addr):
    #             self.bt_led.on()
    #             return True
    #     self.bt_led.on()
    #     return False


#-----------------------------------------------------------
# store the previous trace file into a backup file
# Opens the RSU trace files
# Enable the trace
#-----------------------------------------------------------

    def trace_start(self, interval, rfname, bfname):
        LOG.debug("====> xcV2Xrsu Recording start")

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
          #vi_conn['trace'] = 'OFF'
          if (os.path.isfile(bfname)):
             LOG.debug("===> xcV2Xrsu Recording stop (size: %s)" % os.path.getsize(bfname))
          else:
             LOG.debug("===> xcV2Xrsu Recording failed") 
          if int(conf_options['openxc_vi_trace_number_of_backup']) > 0:   # if SD backup is needed
             self.trace_sd_backup(bfname, bfsize,1)
        self.trace_raw_lock.release()

    def trace_sd_backup(self, bfname, bfsize, v2x_flag):
        # sd backup file
        LOG.debug("SD backup")

        # check for space
        fnum = int(conf_options['openxc_vi_trace_number_of_backup'])
        while (fnum > 0) :
            if self.sd_space < bfsize:
                # remove file to make space
                fname = "%s_%s.%s" % (XCMODEM_SSD_TRACE_PREFIX, fnum, XCMODEM_SSD_TRACE_SUFFIX)
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
             fname1 = "%s_%s.%s" % (XCMODEM_SSD_V2X_TRACE_PREFIX, fnum, XCMODEM_SSD_TRACE_SUFFIX)
            else:
             fname1 = "%s_%s.%s" % (XCMODEM_SSD_TRACE_PREFIX, fnum, XCMODEM_SSD_TRACE_SUFFIX)
            fnum -= 1
            if v2x_flag:
             fname2 = "%s_%s.%s" % (XCMODEM_SSD_V2X_TRACE_PREFIX, fnum, XCMODEM_SSD_TRACE_SUFFIX)
            else:
             fname2 = "%s_%s.%s" % (XCMODEM_SSD_TRACE_PREFIX, fnum, XCMODEM_SSD_TRACE_SUFFIX)
            if os.path.exists(fname2):
                if os.path.exists(fname1):         # gain space
                     self.sd_space += os.path.getsize(fname1)
                # LOG.debug("rename '%s to %s' " % (fname2, fname1))
                os.rename(fname2, fname1)
        # backup recent raw file
        if v2x_flag:
          fname = "%s_1.%s" % (XCMODEM_SSD_V2X_TRACE_PREFIX, XCMODEM_SSD_TRACE_SUFFIX)
        else:
          fname = "%s_1.%s" % (XCMODEM_SSD_TRACE_PREFIX, XCMODEM_SSD_TRACE_SUFFIX)
        cmd = "cp -p %s %s" % (bfname, fname)
        #LOG.debug("issuing '%s' " % cmd)
        if subprocess.call(cmd, shell=True):
            LOG.error("fail to backup %s" % fname)
        else:
            self.sd_space -= bfsize

#------------------------------------------------------------------------------------------------
# Setup up backup drive
#------------------------------------------------------------------------------------------------
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
                   fi" % (XCMODEM_SSD_DEVICE, XCMODEM_SSD_PARTITION, \
                          XCMODEM_SSD_MOUNT, \
                          XCMODEM_SSD_MOUNT, \
                          XCMODEM_SSD_MOUNT, \
                          XCMODEM_SSD_PARTITION, XCMODEM_SSD_MOUNT)
            # LOG.debug("issuing '%s'" % cmd)
            if subprocess.call(cmd, shell=True):
                LOG.error("fail to prepare %s - skip SD backup" % XCMODEM_SSD_MOUNT)
                conf_options['openxc_vi_trace_number_of_backup'] = 0    # Turn off SD backup
            else:
                cmd = "df -BK %s | tail -1 | awk '{print $4}' | awk -FK '{print $1}'" % XCMODEM_SSD_MOUNT
                # LOG.debug("issuing '%s'" % cmd)
                self.sd_space = int(subprocess.check_output(cmd, shell=True).split()[0]) * 1024


#--------------------------------------------------------------------------------------------
#  truncate the file size based on the config parameter
#--------------------------------------------------------------------------------------------
    def trace_prep(self, bfname, fname):
        # make bk file readable so we can present it over network later on
        LOG.debug("Recording conversion")
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

#--------------------------------------------------------------------------------------------
#  Upload log to web
#--------------------------------------------------------------------------------------------
    def web_upload(self, bfname, fname):
        LOG.debug(">>>>>> RSU Web uploading start <<<<<<<")

        if not os.path.exists(bfname):
            LOG.debug("No trace yet to be uploaded") 
            return

        # Prep the trace file
        self.trace_prep(bfname, fname)

        # OXM-93: Need timeout to terminate scp process in case something goes wrong
        timeout = (float(conf_options['openxc_vi_trace_snapshot_duration']) * UPLOAD_TIMEOUT_FACTOR) + UPLOAD_OVERHEAD_TIME

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
        LOG.debug("issuing '%s'" % cmd)
        self.trace_lock.acquire()
        rc = subprocess.call(cmd, shell=True)
        if rc:
            if rc == TIMEOUT_RC:
                msg = "Timeout (%ds)" % int(timeout)
                modem_state[self.name] = app_state.LOST
            else:
                msg = "Fail"
            LOG.error("%s to scp upload %s to %s@%s" % (msg, fname, \
                                                        conf_options['web_scp_userid'], \
                                                        target))
        self.trace_lock.release()

#--------------------------------------------------------------------------------------------
#  tSave the configuration
#--------------------------------------------------------------------------------------------
    def conf_save(self, fname):
        LOG.debug("Configuration saving")
        fp = open(fname, "w+")
        for l in conf_options.items():
            (key, val) = l
            fp.write("%s %s\r\n" % (key, val))
        fp.close()

#--------------------------------------------------------------------------------------------
#  Exit Applicatios: Close scokets, stop monitors, empry Queues
#--------------------------------------------------------------------------------------------
    def xcV2Xrsu_exit(self):
        # clean up function after OPERATION state
        if self.socket:
            self.socket.shutdown(socket.SHUT_RDWR)
            self.socket.close()
            self.socket = None
        if self.send_socket:
            self.send_socket.shutdown(socket.SHUT_RDWR)
            self.send_socket.close()
            self.send_socket = None
        if self.recv_socket:
            self.send_socket.shutdown(socket.SHUT_RDWR)
            self.send_socket.close()
            self.send_socket = None
        if self.stop_trace:
            LOG.debug("Recording end")
            self.stop_trace.set()
        if self.stop_web_upload:
            LOG.debug("Web uploading end")
            self.stop_web_upload.set()
        if self.stop_monitor:
            LOG.debug("Monitor end")
            self.stop_monitor.set()
        if self.fp:
            self.trace_raw_lock.acquire()
            self.fp.close()
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

#--------------------------------------------------------------------------------------------
#  Timestamp the log
#--------------------------------------------------------------------------------------------
    def xcV2Xrsu_timestamp(self, data):
        # add timestamp    
        rstr = ',\"timestamp\":%6f}' % time.time()
        new = string.replace(data, '}', rstr)
        return new

#--------------------------------------------------------------------------------------------
#  Set led brightness
#--------------------------------------------------------------------------------------------
    def led_brightness(self, level):
        # LED Brightness via MAX5432 
        I2C_ADDRESS = 0x28
        REG_VREG = 0x11
        status = self.led_cntl.write_byte_data(I2C_ADDRESS, REG_VREG, level)

#--------------------------------------------------------------------------------------------
#  Set led brightness based on config parameters
#--------------------------------------------------------------------------------------------
    def vi_power_profile(self):
        # power-saving-mode profile - TODO
        mode = conf_options['power_saving_mode']
        LOG.info("Power mode configuration: " + mode)
        self.led_brightness(conf_options['led_brightness'])

#--------------------------------------------------------------------------------------------
#  Main funciton for V2X and RSU communication
#--------------------------------------------------------------------------------------------
    def xcV2Xrsu_main(self):
        attempt = 1

        stuck_state = xcV2Xrsu_state.ADDR_INQUIRY
        stuck_cnt = 0
        self.config_mode = boardmode_inquiry()
        self.boardid     = boardid_inquiry()
        LOG.info("------>    Entering xcV2Xrsu_main  <-----------------")
        LOG.info("Board        = %s"  % self.boardid)
        LOG.info("Config mode  = %s " % self.config_mode)
        LOG.info("-----------------------------------------------")


        if ((self.boardid == 3) and ((self.config_mode == 2) or (self.config_mode == 3))):
            vi_auto_upgrade()
        else:
            if((self.boardid == 2) and ((self.config_mode == 3))):
                v2x_lan_upgrade()
	  
       
        # RSU functionality below  can be used only if the unit is V2X(boardd = 2) 
        # or RSU (boardid = 3) and Config modes being 2 or 3

        # if (boardid_inquiry() > 1) and ((self.config_mode == 2) \
        #                                or (self.config_mode == 3)):
        if (self.boardid  > 1) and \
                 ((self.config_mode == 2) or (self.config_mode == 3)):
          LOG.info("Checking for Modem")
          while (attempt <= MAX_DISCOVERY_ATTEMPT):
            modem_state[self.name] = xcV2Xrsu_state.MODEM_DISCOVERY
            if self.modem_inquiry() is not None:
              modem_state[self.name] = xcV2Xrsu_state.MODEM_ADDR_FOUND
              #LOG.info(" Modem Address found")
              #if (self.modem_available(conf_options['chd_modem_ip_addr'])):
              if (self.modem_available()):
                modem_state[self.name] = xcV2Xrsu_state.MODEM_UP
                LOG.info("Modem is UP")
                if (self.modem_connect()):
                  modem_state[self.name] = xcV2Xrsu_state.MODEM_CONNECTED
                  LOG.info("Modem is connected and Operational")
                  mac_addr = self.get_chd_mac_addr()
                  if (not mac_addr is None) and conf_options['chd_ch_update_enable']:
                    LOG.info("Setting Cohda Link properties from config")
                    cohda_link_setup(self.get_chd_mac_addr())
                break
            if stuck_state != modem_state[self.name]:
                stuck_state = modem_state[self.name]
                stuck_cnt = 1
            else:
                stuck_cnt += 1

            LOG.info("MODEM DISOVERY - %s-state = %s after %d attempt" % (self.modem_state[self.name], attempt))
            attempt += 1
             

          if (modem_state[self.name] == xcV2Xrsu_state.MODEM_CONNECTED):

            # create threads
            # RSU uses UDP socket as aginst BT or STREAM sockets
            thread1 = UdpsockRecvThread("%s-Recv" % self.name, self.recv_socket, self.recv_port, self.inQ, self.name, sflag = 1)
            thread2 = UdpsockSendThread("%s-Send" % self.name, self.send_socket, self.send_port, self.outQ, self.name)
            # start threads
            thread1.start()
            thread2.start()

            self.threads.append(thread1)
            self.threads.append(thread2)

            self.trace_sd_backup_prep()

            # invoke stop_xxx.set() to stop the task if needed
            # start trace task asap
            #------------------------------------------------
            # Start the Trace Control thread
            #------------------------------------------------
            thread3, self.stop_trace = loop_timer(float(conf_options['openxc_xcV2Xrsu_trace_idle_duration']), \
                                         self.trace_start, \
                                         float(conf_options['openxc_xcV2Xrsu_trace_snapshot_duration']), \
                                         XCMODEM_XCV2XRSU_TRACE_RAW_FILE, XCMODEM_XCV2XRSU_TRACE_RAW_BK_FILE)
            self.threads.append(thread3)

            #------------------------------------------------
            # Start Web Upload thread. for web upload, we use the stable back up file
            #------------------------------------------------
            if ((self.boardid == 2) and (self.config_mode == 2)):
                if conf_options['web_scp_xcV2Xrsu_trace_upload_enable']:
                   thread4, self.stop_web_upload = loop_timer(float(conf_options['web_scp_xcV2Xrsu_trace_upload_interval']), \
                                                  self.web_upload, \
                                                  XCMODEM_XCV2XRSU_TRACE_RAW_BK_FILE, XCMODEM_XCV2XRSU_TRACE_FILE) 
                   self.threads.append(thread4)

            #------------------------------------------------
            # start monitor task
            #------------------------------------------------
            monitor_interval = float(power_mode[conf_options['power_saving_mode']]['monitor_interval'])
            thread5, self.stop_monitor = loop_timer(monitor_interval, self.xcV2Xrsu_monitor) 
            self.threads.append(thread5)
            modem_state[self.name] = xcV2Xrsu_state.OPERATION
          else:
            LOG.info("ERROR: 802.11p link is down")
            exit_flag[self.name] = 1
            if stuck_cnt >= MAX_DISCOVERY_ATTEMPT \
                and (stuck_state == xcV2Xrsu_state.ADDR_ASSIGNED):
                LOG.debug("RSU probably stucks! Work-around to re-start the modem")
                LOG.debug("Please restart your test !!")
                
            else:
                modem_state[self.name] = xcV2Xrsu_state.RESTART
#AK  check for ways to restart the cohda
                cohda_cw_llc_restart(self.name)
#                vi_bt_restart(self.name)
            
        LOG.info("v2x_2_xcV2Xrsu.state = %s" % modem_state[self.name])
        return (modem_state[self.name] == xcV2Xrsu_state.OPERATION)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', help='Verbosity Level (0..2)')
    args = parser.parse_args()

    if args.v is None:
        level = 0
    else:
        level = int(args.v)

    xcV2Xrsu_dev =xcV2xRsu(port_dict['v2x_2_rsu']['port'], rsu_in_queue, rsu_out_queue, \
                       sdebug = (level>1), debug = (level>0))
    attempt = 1

    while True:
        if (xcV2Xrsu_dev.xcV2Xrsu_main()):
            while not exit_flag['v2x_2_rsu']:
                xcV2Xrsu_out_queue.put("Hello rsu")
                while not xcV2Xrsu_in_queue.empty():
                    data = xcV2Xrsu_dev.inQ.get()
             
                    # print("rec [%s]" % data)
                    new = xcV2Xrsu_dev.xcV2Xrsu_timestamp(data)    
                    # print("new [%s]" % new)
                    # simply dump into a file 
                    xcV2Xrsu_dev.trace_raw_lock.acquire()
                    if xcV2Xrsu_dev.fp and xcV2Xrsu_dev.trace_enable:
                        xcV2Xrsu_dev.fp.write(new)
                    xcV2Xrsu_dev.trace_raw_lock.release()
                msleep(1)
            modem_state['v2x_2_rsu'] = vi_state.LOST
            xcV2Xrsu_dev.lost_cnt += 1
            LOG.info("v2x_2_rsu state %s %d time" % (modem_state['v2x_2_rsu'], xcV2Xrsu_dev.lost_cnt))
            xcV2Xrsu_dev.xcV2Xrsu_exit()

        if exit_flag['all_app']:
            LOG.debug("Ending all_app")
            break;
        time.sleep(float(conf_options['openxc_vi_discovery_interval']))
        attempt += 1
        if (attempt > MAX_BRING_UP_ATTEMPT):
            LOG.debug("v2x_2_rsu max out %d attempts" % MAX_BRING_UP_ATTEMPT)
            break;
            


