#!/usr/bin/python

import logging
import Queue
import threading
import time
import os.path
import sys
from subprocess import call

sys.path.append('../common')
from xc_common import *
from xc_vi import *
from xc_app import *
from xc_rsu_common import *
import xc_ver
import xc_json

# Configuration
SEND_INTERVAL = 0.5   	# Minimum time between sending each packet (in seconds)
NUM_PACKETS = 10	# The number of packets which will be sent before the script sends its log to the server and closes
LOCAL_LOG = "/home/xplained/"+xc_json.get_mac()+".log"		# Where the local copy of the log is to be kept (best to leave the filename as the MAC)
LOG_SERVER_IP = "192.168.1.148"	# IP Address of the server which stores all of the log files from the nodes
LOG_USER = "pi"		# Username for connecting to the log server
LOG_PW = "raspberry"		# Password for log server
REMOTE_LOG = "/home/pi/node_limit_logs"		# Directory where the log will be  uploaded for processing when the test is complete


logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('nodes_test')

def main(sdebug = 0, debug = 0):
    attempt = 1
    threads = []
    restart = 0
    count = 0

    LOG.info("OpenXC - Max Number of Nodes Test")

    myhost = os.uname()[1]
    mymac = xc_json.get_mac()
    LOG.info(myhost)

    #---------------------------------------
    #   check the current configuration type
    #---------------------------------------
    config_mode = boardmode_inquiry()

    #---------------------------------------
    # RSU integration if mode = 2 or 3
    #---------------------------------------
    if (config_mode == 2) or (config_mode == 3):
        xcV2Xrsu_dev = xcV2Xrsu('v2x_2_rsu',port_dict['xcV2Xrsu_tx']['port'],port_dict['xcV2Xrsu_rx']['port'], xcV2Xrsu_in_queue, xcV2Xrsu_out_queue, sdebug, debug)
        xcV2Xrsu_dev.file_discovery(XCMODEM_CONFIG_FILE)
        #------------------------------
        # Check if RSU is running
        #------------------------------
     	xcV2Xrsu_status = xcV2Xrsu_dev.xcV2Xrsu_main(); 
     	while ( not xcV2Xrsu_status)and (attempt < MAX_BRING_UP_ATTEMPT):
            time.sleep(float(conf_options['openxc_vi_discovery_interval']))
            attempt += 1
            xcV2Xrsu_status = xcV2Xrsu_dev.xcV2Xrsu_main() 

        if (not xcV2Xrsu_status):
            LOG.debug("v2x_2_rsu  max out %d attempts" % MAX_BRING_UP_ATTEMPT)
            sys.exit()
    msleep(2000)
    msg_num = 1
    with open(LOCAL_LOG, 'w') as fptr:
    	fptr.write("R:<source mac>,<msg #>,<recv. time> - One packet received by this device\n")
	fptr.write("S:<my mac>,<msg #>,<time packet generated> - One packet sent by this device\n")
	while msg_num <= NUM_PACKETS:
        	msleep(1000 * SEND_INTERVAL)    # Wait to send the next packet
		message_out = xc_json.JSON_msg_encode("Node_Count", msg_num, {}, [mymac, 0, 1, 0])
        	xcV2Xrsu_out_queue.put(message_out)
		data_dict = xc_json.JSON_msg_decode(message_out)
		print ("Message #%d sent" % msg_num)
        	fptr.write("S:{0},{1},{2}\n".format(mymac, msg_num, data_dict["meta"]["timestamp"]))  # Log that packet was sent

		while not xcV2Xrsu_in_queue.empty():
			message_in = xcV2Xrsu_in_queue.get()
			in_dict = xc_json.JSON_msg_decode(message_in)
			fptr.write("R:{0},{1},{2}\n".format(in_dict["meta"]["source"], in_dict["value"], time.time()))	# Log packet picked up and where it came from
		msg_num = msg_num + 1

    fptr.close()	# Do we need to close for writing then re-open for reading?
    # Upload log, print on success
    os.system('sshpass -p "{0}" scp "{1}" "{2}@{3}:{4}/{5}.log"'.format(LOG_PW,LOCAL_LOG,LOG_USER,LOG_SERVER_IP,REMOTE_LOG,xc_json.get_mac())) 
    LOG.debug("Succesfully wrote {0}.log to server!".format(xc_json.get_mac()))
    
    cmd = "kill -KILL %d" % os.getpid()
    subprocess.call(cmd, shell=True)    # Quick and dirty way to stop everything
    sys.exit()  # Should never make it here, but just in case

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', help='Verbosity Level (-2..2)')
    args = parser.parse_args()
    restart = 1;

    if args.v is None:
        level = 0
    else:
        level = int(args.v)

    if level < -1:
        LOG.setLevel(level=logging.WARN)
    elif level < 0:
        LOG.setLevel(level=logging.INFO)
    main(sdebug = (level>1), debug = (level>0))
        
