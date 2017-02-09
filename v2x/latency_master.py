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
SEND_INTERVAL = 0.5   # Time between one test and starting the next
NUM_ROUNDS = 10		# The number of times messages should be sent back and forth before the data is tabulated

logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('latency_test_master')

def main(sdebug = 0, debug = 0):
    attempt = 1
    threads = []
    restart = 0
    count = 0

    LOG.info("OpenXC - Latency Test Master")

    myhost = os.uname()[1]
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
    msg_num = 0
    time_sum = 0
    while msg_num < NUM_ROUNDS:
        msleep(1000 * SEND_INTERVAL)    # Wait to send the next packet
	message_out = xc_json.JSON_msg_encode("Latency_Test", msg_num, {}, [xc_json.get_mac(), 0, 1, 0])
        print ("Transmitting:  [[ %s ]]" % message_out)
	start_time = time.time()
        xcV2Xrsu_out_queue.put(message_out);

	while xcV2Xrsu_in_queue.empty(): pass
	stop_time = time.time()
	message_in = xcV2Xrsu_in_queue.get()
	in_dict = xc_json.JSON_msg_decode(message_in)
	if in_dict["value"] == msg_num:
		latency = stop_time - start_time
		print "Latency for Round #%d: %f seconds" % (msg_num+1, float(latency))
		time_sum = time_sum + latency
	else:
		print "Got a packet and the value doesn't match!"
	msg_num = msg_num + 1

    avg_time = float(time_sum / NUM_ROUNDS)
    print "Average round-trip latency over %d runs was %f seconds" % (NUM_ROUNDS, avg_time)

    print "Telling slave to close..."
    xcV2Xrsu_out_queue.put(xc_json.JSON_msg_encode("Latency_Test","Quit",{},[xc_json.get_mac(), 0, 1, 0]))
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
        
