# $Rev:: 242           $
# $Author:: mlgantra   $
# $Date:: 2015-04-03 1#$
#
# openXC-modem common functions

import Queue
import threading
import time
import argparse
import logging
import logging.handlers
import subprocess
import os
import re
import socket
import select
#from rsu_fn import *
import re

from bluetooth.btcommon import BluetoothError




#
# logging into /var/log/syslog
#  
logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('xcmodem')
sh = logging.handlers.SysLogHandler(address = '/dev/log')
sh.setFormatter(logging.Formatter('%(name)s[%(process)d] - %(levelname)s - %(message)s'))
LOG.addHandler(sh)



def configure_logging(level=logging.WARN):
    logging.getLogger("xcmodem").addHandler(logging.StreamHandler())
    logging.getLogger("xcmodem").setLevel(level)



OPENXC_V2X_NAME_PREFIX = "OpenXC-VI-V2X-"
OPENXC_MODEM_NAME_PREFIX = "OpenXC-VI-MODEM-"
OPENXC_DEVICE_NAME_PREFIX = "OpenXC-VI-"


MAX_DISCOVERY_ATTEMPT = 3
MAX_CONNECTION_ATTEMPT = 3
MAX_BRING_UP_ATTEMPT = 1000


SERIAL_INTERFACE_TIMEOUT = 0.3        # Should be enough to accomodate several requests per second



# Enum simple implement
class Enum(set):
    def __getattr__(self, name):
        if name in self:
            return name
        raise AttributeError

# OpenXC-vi_app status
vi_state = Enum(['IDLE', 'DISABLE', 'ADDR_INQUIRY', 'ADDR_ASSIGNED', 'DISCOVERED', 'CONNECTED', 'OPERATION', 'LOST', 'RESTART', 'MODEM_DISCOVERY', 'MODEM_ADDR_FOUND', 'MODEM_UP', 'MODEM_CONNECTED'])

# OpenXC-md_app status
#md_state = Enum(['IDLE', 'DISABLE', 'ADDR_INQUIRY', 'ADDR_ASSIGNED', 'DISCOVERED', 'CONNECTED', 'OPERATION', 'LOST', 'RESTART'])


# OpenXC-rsu_app status
xcV2Xrsu_state = Enum(['IDLE','RESTART', 'ADDR_INQUIRY', 'MODEM_DISCOVERY', 'MODEM_ADDR_FOUND', 'MODEM_UP', 'MODEM_CONNECTED', 'OPERATION', 'LOST'])

# App status
app_state = Enum(['IDLE', 'PENDING', 'CONNECTED', 'LOCKING', 'OPERATION', 'DONE', 'LOST'])

# Charger status
charge_state = Enum(['IDLE', 'NOT_CHARGE', 'PRE_CHARGE', 'FAST_CHARGE', 'CHARGE_DONE'])


#------------------------------------------------------------------
# Use the hidden file .xcmodem_boardid to indicate the board type 
#------------------------------------------------------------------
XCMODEM_BOARDID_FILE = '../common/.xcmodem_boardid'        # hidden file
XCMODEM_MODE_FILE    = '../common/xcmodem_topology'        # Topology setup file

#------------------------------------------------------------------
# Device type file
#------------------------------------------------------------------
board_type = {
    0:  {'type': 'MODEM-EVT', 'prefix': 'OpenXC-VI-MODEM'},  # OpenXC-Modem EVT
    1:  {'type': 'MODEM-DVT', 'prefix': 'OpenXC-VI-MODEM'},  # OpenXC-Modem DVT
    2:  {'type': 'V2X'      , 'prefix': 'OpenXC-VI-V2X'},    # OpenXC-V2X
    3:  {'type': 'RSU'      , 'prefix': 'OpenXC-VI-RSU'}     # OpenXC-RSU
}

#------------------------------------------------------------------
# Static rfcomm port assignment
#------------------------------------------------------------------
port_dict = {
    'vi_app'     :{'port': 1,    'enable': 1}, # for OpenXC_vi_app device
    'pc_app'     :{'port': 21,   'enable': 0}, # for OpenXCModem PC Application
    'mb_app'     :{'port': 22,   'enable': 1}, # for OpenXCModem Mobile Application
    'm_2_v2x'    :{'port': 4567, 'enable': 1}, # for OpenXCModem to v2x communicaiton
    'v2x_2_m'    :{'port': 4567, 'enable': 1}, # for OpenXCModem to v2x communicaiton

    'xcV2Xrsu_tx':{'port': 7777, 'enable': 1}, # for xcV2Xrsu Trasnmist
    'xcV2Xrsu_rx':{'port': 7777, 'enable': 1}, # for xcV2Xrsu receive 

#    'v2x_2_rsu' :{'port': 7777, 'enable': 1}, # for v2x  to rsu communicaiton
#    'rsu_2_v2x' :{'port': 7777, 'enable': 1}, # for rsu  to v2x communicaiton
#    'md_app'    :{'port': 23,   'enable': 0},  # for OpenXCModem V2X-MD Application
#    'v2x_vehicle_app':{'port': 0, 'enable': 1} # for OpenXC RSU demo application
}

# mb status
mb_status = {
   'vi_id_sent'            : False,            # for OpenXCModem Mobile Application
   'vi_version_sent'       : False,            # for OpenXCModem PC Application
   'modem_id_sent'         : False,            # for OpenXCModem Mobile Application
   'modem_version_sent'    : False,            # for OpenXCModem PC Application
   'v2x_id_sent'           : False,            # for OpenXCModem Mobile Application
   'v2x_version_sent'      : False,            # for OpenXCModem PC Application
   'ready'	            : False
}

#------------------------------------------------------------------
# VI data stream pass-thru mode 
#------------------------------------------------------------------
vi_bypass = {
    'mb_app'        : True,            # for OpenXCModem Mobile Application
    'pc_app'        : True,            # for OpenXCModem PC Application
    'modem_app'     : False,            # for OpenXCModem modem Application for V2X
    'xcV2Xrsu_app'  : True
}

#------------------------------------------------------------------
# VI Passthru support nable flag 
#------------------------------------------------------------------
passthru_enable = {
    'mb_app': 1,                # for OpenXCModem Mobile Application
    'md_app': 0                 # for OpenXCModem V2X-MD Application - No support
}

#------------------------------------------------------------------
# Passthru effective flag
#------------------------------------------------------------------
passthru_flag = {
    'mb_app': 1,                # for OpenXCModem Mobile Application
    'md_app': 0,                 # for OpenXCModem V2X-MD Application
}


#------------------------------------------------------------------
# port MAC status
#------------------------------------------------------------------
port_mac = {
    'vi_app': None,             # for OpenXC_vi_app device
    'pc_app': None,             # for OpenXCModem PC Application
    'mb_app': None,             # for OpenXCModem Mobile Application
    'wf_app': None              # for OpenXCModem WiFi/V2X Application
}

#------------------------------------------------------------------
# V2X-MD app info
#------------------------------------------------------------------
md_dict = {
    'id'   : None,
    'ver'  : None,
    'hbeat': None
}

#------------------------------------------------------------------
# V2X-V2X app info
#------------------------------------------------------------------
wf_dict = {
    'id'   : None,
    'ver'  : None,
    'hbeat': None
}


#------------------------------------------------------------------
# Current modem state for diagnostic message
#------------------------------------------------------------------
modem_state = {
    'vi_app'   : vi_state.IDLE,
    'gps_app'  : app_state.IDLE,
    'gsm_app'  : app_state.IDLE,
    'pc_app'   : app_state.IDLE,
    'mb_app'   : app_state.IDLE,
    'm_2_v2x'  : app_state.IDLE,
    'xcV2Xrsu': app_state.IDLE,
#    'v2x_2_rsu': app_state.IDLE,
    'charger'  : charge_state.IDLE
}

#------------------------------------------------------------------
# Configuration File dictionary
#------------------------------------------------------------------
conf_options = {
    'openxc_modem_mac'     		      : 'None',
#    'openxc_md_mac'                           : 'None',                   # only appliable for V2X
    'openxc_md_enable'                        : 1,                     # 1/0 by default for Modem/V2X
    'openxc_vi_mac'                           : 'None',
    'openxc_vi_enable'                        : 1, 

    'openxc_vi_trace_snapshot_duration'       : 10,
    'openxc_v2x_trace_snapshot_duration'      : 10,
    'openxc_vi_trace_idle_duration'           : 110,
    'openxc_v2x_trace_idle_duration'          : 110,
    'openxc_vi_trace_truncate_size'           : 0,        # zero means no truncate
    'openxc_vi_trace_filter_script'           : 'None',   # executable shell script
    'openxc_vi_trace_number_of_backup'        : 1,     # zero means no backup
    'openxc_vi_trace_backup_overwrite_enable' : 0,
    'openxc_vi_discovery_interval'            : 10,
    'web_scp_userid'                          : 'ubuntu',
    'v2x_lan_scp_userid'		      : 'root',
#    'web_scp_pem'                             : 'xcmodem.pem',
    'web_scp_pem'                             : 'xc_scp.pem',
    'web_scp_apn'                             : 'apn',
    'web_scp_config_url'                      : 'ip_address:file',
    'web_scp_config_download_enable'          : 0,
#    'web_scp_target_url' : 'ip_address:file',
    'web_scp_vi_target_url'                   : '54.187.136.160:~/public_html/tracedata/vi_trace.json',
    'web_scp_target_overwrite_enable'         : 1,
    'web_scp_vi_trace_upload_enable'          : 1,
#    'web_scp_trace_upload_interval': 3600,
    'web_scp_vi_trace_upload_interval'        : 40,
    'web_scp_sw_latest_version_url'           : '54.187.136.160:~/web/release/xc-upgrade.version',
    'v2x_lan_scp_sw_latest_version_url'       : '20.0.0.1:/tmp/upgrade.ver',
    'fw_factory_reset_enable'                 : 1,
    'power_saving_mode'                       : 'normal',
    'led_brightness'                          : 128,        # for normal of power_saving_mode

    'gps_log_interval'                        : 10,
    'gps_enable'                              : 0,    # These are mainly for emulation purpose
    'gsm_enable'                              : 0,     # production board should be correctly configured

     #*************************
     # V2XRSU options
     #*************************
    'openxc_xcV2Xrsu_trace_snapshot_duration' : 120, # Duration of capture
    'openxc_xcV2Xrsu_trace_idle_duration'     : 10, # interval between capture
    'web_scp_xcV2Xrsu_target_url'             : '54.187.136.160:~/public_html/tracedata/rsu_trace.json',
                                                # url where the trace is uploaded
    'web_scp_xcV2Xrsu_trace_upload_interval'  : 200, # interval between web upload
    'web_scp_xcV2Xrsu_trace_upload_enable'    : 1,   # control variable for web upload
    'openxc_xcV2Xrsu_msg_send_interval'       : 20,  # interval between RSU messages being sent out
    'xcmodem_ip_addr'                         : '20.0.0.1',     # i Address for the xc_modem device
    
     #*************************
     # COHDA Channel parameters
     #*************************

    'chd_txpower'          : 2,   # power in dbm
    'chd_radio'            : 'a', # could be radio a or radio b
    'chd_antenna'          : '3', # antenna could be   1, 2, 3
    'chd_chan_no'          : 184, # channel no coud be (172, 174, 176, 180, 182, 184) for 10 MHz channels
                               # or (175, 181) for 20MHz Channel. All these channels are SCH
                               # default is 184
    'chd_modulation'       : 'MK2MCS_R12QPSK', # possible values - "MK2MCS_R12BPSK | MK2MCS_R34BPSK | MK2MCS_R12QPSK 
                               # | MK2MCS_R34QPSK | MK2MCS_R12QAM16 | MK2MCS_R34QAM16 | MK2MCS_R23QAM64 
                               # | MK2MCS_R34QAM64 | MK2MCS_DEFAULT | MK2MCS_TRC" 
    'chd_ch_update_enable' : 0
   
}

#------------------------------------------------------------------
# termination signal
#------------------------------------------------------------------
exit_flag = {
    'vi_app'        :0,
    'pc_app'        :0,
    'mb_app'        :0,
    'all_app'       :0,   # force flag to terminate ALL app
    'bt_restart'    :0,   # force flag for BlueTooth restart
    'vi_src_switch' :0,
    'v2x_2_rsu'     :0,
    'rsu_2_v2x'     :0
}

#------------------------------------------------------------------
vi_conn = {
     'type'  : 'NONE',
     'state' : 'NOT_SET',
     'trace' : 'OFF'
}

#------------------------------------------------------------------
# gps information
#------------------------------------------------------------------
gps_dict = {
    'utc' : None, 
    'date': None,
    'lat' : None,
    'lon' : None,
    'alt' : None
}

#------------------------------------------------------------------
# gsm information
#------------------------------------------------------------------
gsm_dict = {
    'rssi': None,
    'ber' : None
}


#------------------------------------------------------------------
# Power-saving mode (performance / normal / saving)
#------------------------------------------------------------------
power_mode = {
    'performance': {'ppp_tear_off': 0, 'monitor_interval': 2, 'led_brightness' : 255},
    'normal':      {'ppp_tear_off': 0, 'monitor_interval': 5, 'led_brightness' : 128},
    'saving':      {'ppp_tear_off': 1, 'monitor_interval': 10, 'led_brightness': 0}
}

#------------------------------------------------------------------
# LED directory path per boardid
#------------------------------------------------------------------
led_path = {
    'bat_grn': { 0: 'd10_grn', 1: 'bat_grn'},
    'bat_red': { 0: 'd10_red', 1: 'bat_red'},
    'bt':      { 0: 'd11'    , 1: 'bt'},
    'gps':     { 0: 'd12'    , 1: 'gps'},
    'wifi':    { 0: 'd13'    , 1: 'wifi'},
    'gsm':     { 0: 'd14'    , 1: 'r2_3g'}
}


usleep = lambda x: time.sleep(x/1000000.0)
msleep = lambda x: time.sleep(x/1000.0)

#------------------------------------------------------------------
# Socket handling threads
#------------------------------------------------------------------
class sockSendThread (threading.Thread):
    def __init__(self, name, socket, queue, eflag):
        threading.Thread.__init__(self)
        self.name = name
        self.sock = socket
        self.queue = queue
        self.eflag = eflag
        self.msgno = 0
    def run(self):
        LOG.debug("Starting " + self.name)
        while not exit_flag[self.eflag]:
            while not self.queue.empty():
                try:
                    data = self.queue.get()
                    self.msgno = self.msgno + 1
                    #if not (data.find("V2X") == -1):
                    #  print("==============================================")
                    #  print(" sending  %d to %s-->>>: %s" % (self.msgno,self.name,data))
                    #if not (data.find("V2X") == -1):
                    #  print("==============================================")
                    self.sock.send(data)
                    #if (self.name == 'mb_app'):
                    #print("%s [%s]\n" % (self.name, data))
                except IOError as e:
                    exit_flag[self.eflag] = 1
                    LOG.debug("%s %s" % (self.name, e))
                    break
            msleep(1)
        LOG.debug("disconnected " + self.name)

#------------------------------------------------------------------
class sockRecvThread (threading.Thread):
    def __init__(self, name, socket, queue, eflag, sflag = 0):
        threading.Thread.__init__(self)
        self.name = name
        self.sock = socket
        self.queue = queue
        self.eflag = eflag
        self.sflag = sflag
    def run(self):
        LOG.debug("Starting " + self.name)
        #self.sock.settimeout(1)
        while not exit_flag[self.eflag]:
            try:
                data = self.sock.recv(1024)
                # print("%s [%s]\n" % (self.name, data))
                self.queue.put(data)
            except BluetoothError as e:
                if e.args[0] == 'timed out':
                    if not self.sflag:
                        continue
                    LOG.debug("timeout stop " + self.name)
                else:
                    LOG.debug("%s %s" % (self.name, e))
                exit_flag[self.eflag] = 1
                break
        LOG.debug("disconnected " + self.name)


#------------------------------------------------------------------
# Socket handling threads
class sockDualSendThread (threading.Thread):
    def __init__(self, name, socket, queue,cmdQ, eflag):
        threading.Thread.__init__(self)
        self.name = name
        self.sock = socket
        self.queue = queue
        self.cmdQ =  cmdQ
        self.eflag = eflag
        self.msgno = 0
    def run(self):
        LOG.debug("Starting " + self.name)
        while not exit_flag[self.eflag]:
            while (not self.queue.empty()) or (not self.cmdQ.empty()) :
                try:
                    data = None
                    if (mb_status['ready']):
                       data = self.queue.get()
                    else:
                      if not self.cmdQ.empty():
                       data = self.cmdQ.get()
                    if (not data is None):
                     self.msgno = self.msgno + 1
                     #if not (data.find("V2X") == -1):
                      #print("==============================================")
                     #print(" sending  %d to %s-->>>: %s" % (self.msgno,self.name,data))
                     #if not (data.find("V2X") == -1):
                      #print("==============================================")
                     if not data.endswith(chr(0)):
                      data = data + chr(0)
                     self.sock.send(data)
                     #if (self.name == 'mb_app'):
                     #print("%s [%s]\n" % (self.name, data))
                    else:
                     LOG.info(">>>>>>   Data is None <<<<<<<<")
                except IOError as e:
                    exit_flag[self.eflag] = 1
                    LOG.debug("%s %s" % (self.name, e))
                    break
            msleep(1)
        mb_status['ready'] = False
        while (not self.queue.empty()):
            data = self.queue.get()
        while (not self.cmdQ.empty()):
            data = self.cmdQ.get()
        LOG.debug("disconnected " + self.name)

def sockSend (name, sock, data, eflag):
    try:
        sock.send(data)
        # print("%s [%s]" % (name, data))
    except IOError as e:
        exit_flag[eflag] = 1
        LOG.debug("%s %s" % (name, e))
        return False
    return True
#------------------------------------------------------------------

# Socket handling threads
class UdpsockSendThread (threading.Thread):
    def __init__(self, name, socket, port, queue, eflag):
        threading.Thread.__init__(self)
        self.name = name
        self.sock = socket
        self.queue = queue
        self.eflag = eflag
        self.port = port
    def run(self):
        LOG.debug("Starting " + self.name)
        #LOG.info("Send port is %s " % self.port)
        while not exit_flag[self.eflag]:
            while not self.queue.empty():
                try:
                    data = self.queue.get()
                    if not data.endswith(chr(0)): # If it doesn't end with a null, add one
                        data = data+chr(0)
                    self.sock.sendto(data, ('<broadcast>',self.port))
#                    print("%s [%s]\n" % (self.name, data))
                except IOError as e:
                    exit_flag[self.eflag] = 1
                    LOG.debug("%s %s" % (self.name, e))
                    break
            msleep(1)
        LOG.debug("disconnected " + self.name)
#------------------------------------------------------------------
class UdpsockRecvThread (threading.Thread):
    def __init__(self, name, socket, port, queue, eflag, sflag = 0):
        threading.Thread.__init__(self)
        self.name = name
        self.sock = socket
        self.queue = queue
        self.eflag = eflag
        self.sflag = sflag
        self.port = port
    def run(self):
        LOG.debug("Starting " + self.name)
        #self.sock.settimeout(1)
        while not exit_flag[self.eflag]:
            try:
                result = select.select([self.sock],[],[])
                data = result[0][0].recv(1024)
                self.queue.put(data)
                
            except BluetoothError as e:
                if e.args[0] == 'timed out':
                    if not self.sflag:
                        continue
                    LOG.debug("timeout stop " + self.name)
                else:
                    LOG.debug("%s %s" % (self.name, e))
                break
        LOG.debug("disconnected " + self.name)

#------------------------------------------------------------------
def loop_timer(interval, function, *args, **kwargs):
    stop_event = threading.Event()

    def loop():        # do ... while implementation
        while True:
            function(*args, **kwargs)
            if stop_event.wait(interval):
                break

    t = threading.Thread(target=loop)
    t.daemon = True
    t.start()
    return t, stop_event


#------------------------------------------------------------------
def pairing_registration():
     # Enable inquiry + pagge scan
     subprocess.call('hciconfig hci0 piscan noauth', shell=True)

     # Simple agent registration for bluetooth pairing
     cmd = 'ps a | grep "bluez-simple-agent" | grep -v grep'
     if subprocess.call(cmd, shell=True, stdout=subprocess.PIPE):
        cmd = 'echo "1234" | bluez-simple-agent hci0 &'
        subprocess.call(cmd, shell=True, stdout=subprocess.PIPE)

#------------------------------------------------------------------

def boardid_inquiry(debug = 0):
    id = 0
    if os.path.exists(XCMODEM_BOARDID_FILE):
        cmd = "cat %s" % XCMODEM_BOARDID_FILE
        id = int(subprocess.check_output(cmd, shell=True).split()[0])
        if board_type.get(id) is None:
            LOG.error("%s isn't a valid board id in %s - skip it !!" % (id, XCMODEM_BOARDID_FILE))
            id = 0
    if debug:
        LOG.info("Board " + board_type[id]['type'])
    return id

#------------------------------------------------------------------
def boardmode_inquiry(debug = 0):
    id = 0
    if os.path.exists(XCMODEM_MODE_FILE):
        cmd = "cat %s" % XCMODEM_MODE_FILE
        id = int(subprocess.check_output(cmd, shell=True).split()[0])
#        if board_type.get(id) is None:
#            LOG.error("%s isn't a valid board id in %s - skip it !!" % (id, XCMODEM_BOARDID_FILE))
#            id = 0
    if debug:
        LOG.info("Board " + board_type[id]['type'])
    return id


#------------------------------------------------------------------
def modem_sock_inquiry():
    flag = 0;
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
    	s.connect(('192.168.1.10', 4567))
        flag = 1
   	LOG.info("191:168.1.10:Port 4567 reachable")
    except socket.error as e:
    	LOG.info("Error on connect 191:168.1.10 on port 4567:: %s" % e)
    s.close()
    return flag

#------------------------------------------------------------------
def cleanup_json(jin):

    jout =  re.search(r'\{(.*)\}+',jin)

    if not jout is None:
      return jout.group(0)
    else:
      return None


#------------------------------------------------------------------
def filter_msg(stro, fid):
  stro = stro.replace("}"+chr(0)+"{","}"+chr(0)+"[]{")
  str_arr = stro.split("[]")

  no=len(str_arr)
  i = 0

  out_str=""
  while (i <no):
   if not fid in str_arr[i]:
    #print str_arr[i]
    out_str = out_str + str_arr[i]
   else:
    pass
    #LOG.info(" Throwing away %s" % (str_arr[i]))
   i=i+1
  return out_str

#=================================================================================
COHDA_INTERFACE_NAME      = "cw-llc"
COHDA_INTERFACE_MTU       = 1500
COHDA_LLC_PATH            = '/root/cohda/app/llc'
COHDA_KO_PATH             =  '/root/cohda/kernel/drivers/cohda/llc/cw-llc.ko'
COHDA_FW_PATH             =  '/lib/firmware/SDRMK5Dual.bin'

#-----------------------------------------------------
# allowed values
#------------------------------------------------------
allowed_channels     = set([172, 174, 176, 180, 182, 184, 175, 181])
allowed_radios       = set(['a', 'b'])
allowed_antenna      = set(['1', '2', '3'])
allowed_txpower_low    = -10 
allowed_txpower_high   = 10 
allowed_modulation   = set(['MK2MCS_R12BPSK' , 'MK2MCS_R34BPSK' ,'MK2MCS_R12QPSK', 'MK2MCS_R34QPSK', \
                            'MK2MCS_R12QAM16' , 'MK2MCS_R34QAM16',  'MK2MCS_R23QAM64', 'MK2MCS_R34QAM64',\
                            'MK2MCS_DEFAULT', 'MK2MCS_TRC'])

#-----------------------------------------------
# Cohda setup routines
#-----------------------------------------------
def cohda_link_setup(chd_mac_addr):

   chd_mtu = 1500
   chd_chan_no    = conf_options['chd_chan_no']
   chd_radio      = conf_options['chd_radio']
   chd_antenna    = conf_options['chd_antenna']
   chd_txpower    = conf_options['chd_txpower']
   chd_modulation = conf_options['chd_modulation']

   llc_path = "/root/cohda/app/llc"
   llc_cmd = "/root/cohda/app/llc/llc"
   
   # verify the options
   if (not chd_chan_no in allowed_channels):
      LOG.info("Illegal channel specification for 802.11p in config file : %d " % chd_chan_no)
      LOG.info("setting the channel to default channel 184")
      chd_chan_no = 184

   if (not chd_radio in allowed_radios):
      LOG.info("Illegal radio specifiication in config file %s " % chd_radio)
      LOG.info("settingthe radio to default value a")
      chd_radio = 'a'

   if (not chd_modulation in allowed_modulation):
      LOG.info("illegal modulation type specified in the config file %s " % chd_modulation)
      LOG.info("setting the modulation to default value MK2MCS_R12QPSK")
      chd_modulation = 'MK2MCS_R12QPSK' 

   if (not chd_antenna in allowed_antenna):
      LOG.info("illegal antenna type specified in the config file %s " % chd_antenna)
      LOG.info("setting the modulation to default value 3")
      chd_antenna = '3' 

   if (not ((chd_txpower < allowed_txpower_high) and (chd_txpower > allowed_txpower_low))):
      LOG.info("illegal power type specified in the config file %s " % chd_txpower)
      LOG.info("setting the modulation to default value 3")
      chd_txpower = '-10' 


   # issue the command
   cmd = "cd "+ llc_path + "; "  + llc_cmd + " chconfig -s -w SCH -c " +  str(chd_chan_no) + " -r " + chd_radio + " -e 0x88b6 -a " + chd_antenna +  " -p " + str(chd_txpower) + " -f " + chd_mac_addr  + " --defaultMCS " +  chd_modulation
   resp = subprocess.call(cmd, shell=True)
   LOG.info("cmd: " + cmd)

#=====================================================


#-----------------------------------------------
# Global queue for passing data
#-----------------------------------------------
vi_in_queue        = Queue.Queue()
vi_out_queue       = Queue.Queue()
mb_in_queue        = Queue.Queue()
mb_out_queue       = Queue.Queue()
mb_passthru_queue  = Queue.Queue()
md_in_queue        = Queue.Queue()
md_out_queue       = Queue.Queue()
md_passthru_queue  = Queue.Queue()
wf_in_queue        = Queue.Queue()
wf_out_queue       = Queue.Queue()
pc_in_queue        = Queue.Queue()
pc_out_queue       = Queue.Queue()
modem_in_queue     = Queue.Queue()
modem_out_queue    = Queue.Queue()
modem_vi_out_queue = Queue.Queue()
xcV2Xrsu_in_queue  = Queue.Queue()
xcV2Xrsu_out_queue = Queue.Queue()
passQ = Queue.Queue()
#-----------------------------------------------
# Global Variables
#-----------------------------------------------
#glb_id         = False
#glb_version    = False
#glb_id_version = False
