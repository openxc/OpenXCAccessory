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

DESIRED_CHANNEL = 184 # Choices: 172, 174, 175, 176, 180, 181, 182, 184)
PACKETS_PER = 10    # Number of packets to send in each burst
PACKET_DELAY = .5   # Delay between packets in a burst (in seconds)

logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('Range_Master')

def main(sdebug = 0, debug = 0):
    attempt = 1
    threads = []
    restart = 0

    LOG.info("OpenXC-V2X Range Tester 2.0 - Master")

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
    while True:
        signal = raw_input("Enter an integer signal strength (or 'Q' to exit): ")
        while not (signal == 'Q' or signal == 'q'): # If the input is Q or q exit
            LOG.info("Setting TxPower setting: to %d (%.1f dBm)" % (int(signal), float(signal)/2))
            cmd = "cd /root/cohda/app/llc ; ./llc chconfig -s -w SCH -c %d -r b -p %d" % (DESIRED_CHANNEL, int(signal))
            subprocess.call(cmd, shell=True)
            msleep(500)
            distance = raw_input("Input the distance (in ft) between the devices and press <Enter> to send {0} packets at {1} dBm (or 'Q' to go up a level): ".format(PACKETS_PER, signal))
            while not (distance == 'Q' or distance == 'q'):
                for count in range(PACKETS_PER):
                    out_msg = xc_json.JSON_msg_encode("Range_Test", count+1, {"power": signal, "dist_ft": distance}, [xc_json.get_mac(), 0, 1, 0])
                    LOG.info ("Sending packet {0} of {1}".format(count+1, PACKETS_PER))
                    xcV2Xrsu_out_queue.put(out_msg);
                    msleep(PACKET_DELAY*1000)
                distance = raw_input("Input the distance (in ft) between the devices and press <Enter> to send {0} packets at {1} dBm (or 'Q' to go up a level): ".format(PACKETS_PER, signal))
            signal = raw_input("Enter an integer signal strength (or 'Q' to exit): ")

        out_msg = xc_json.JSON_msg_encode("Range_Test", "Quit", {}, [xc_json.get_mac(), 0, 1, 0])
        LOG.info("Instructing slave to exit");
        xcV2Xrsu_out_queue.put(out_msg);
        msleep(1000)    # Give the device some time to send the last packet
        # terminate all threads
        LOG.info("Terminating all threads")
        for k in exit_flag.keys():
            exit_flag[k] = 1
        msleep(5000)
        # Wait for all threads to complete
        LOG.info("Waiting for all threads to join")
        for t in threads:
            t.join()
        LOG.info("Quitting..")
        cmd = "kill -KILL %d" % os.getpid() # This isn't elegant, but it does succesfully stop the process every time
        subprocess.call(cmd, shell=True)

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
