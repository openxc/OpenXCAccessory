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
from cleanup import *
import xc_json

PACKETS_PER = 20    # Number of packets to in each burst
PACKET_DELAY = 0.25   # Delay between packets in a burst (in seconds)
TIMEOUT = 15   # Number of seconds to allow for a complete burst before the remaining packets are considered to have failed automatically
THRESHOLD = 0.5    # Minimum percentage of packets which must make it through for a burst to be succesful
LOGFILE = "/home/xplained/range_test.log"       # Location of the logfile for recording power settings and distances

logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('Range_Slave')

def main(sdebug = 0, debug = 0):
    restart = 0
    rsu_dev = None
    myhost = os.uname()[1]

    LOG.info("OpenXC-V2X Range Tester 2.0 - Slave")

    # If the directory doesn't exist we can't even create the file
    directory = LOGFILE.split('/')
    directory = '/'.join(directory[0:len(directory)-1])
    if not os.path.isdir(directory):
        LOG.error("The logfile indicated is not in a directory that exists!  Please correct and restart")
        return

    # If the file doesn't exist, create it, add the header, and close it
    if not os.path.isfile(LOGFILE):
        fptr = open(LOGFILE,'w')
        fptr.write("Power (dBm),Distance (ft),Rcvd. Packs,Total Packs\n")
        fptr.close()

    #---------------------------------------
    #   check the current configuration type
    #---------------------------------------
    config_mode = boardmode_inquiry()

    #---------------------------------------
    # RSU integration code
    #---------------------------------------
    if (config_mode == 2) or (config_mode == 3):
        rsu_dev = xcV2Xrsu('rsu_2_v2x', port_dict['xcV2Xrsu_tx']['port'],port_dict['xcV2Xrsu_rx']['port'], xcV2Xrsu_in_queue, xcV2Xrsu_out_queue, sdebug, debug)

    #----------------------------------------
    # RSU is up. Run the main loop
    #----------------------------------------
    if (rsu_dev.xcV2Xrsu_main()):
        while True:
            while xcV2Xrsu_in_queue.empty(): pass
            rcvd_arr = [False] * PACKETS_PER
            num_rcvd = 0
            cutoff = float('inf')
            while num_rcvd < PACKETS_PER and time.time() < cutoff:
                fptr = open(LOGFILE,'a')
                while not xcV2Xrsu_in_queue.empty():
                    tdata = xcV2Xrsu_in_queue.get()
                    in_dict = xc_json.JSON_msg_decode(tdata)
                    if in_dict["value"] == "Quit":
                        fptr.close()
                        LOG.info("Received instruction to quit!")
                        cmd = "kill -KILL %d" % os.getpid()
                        subprocess.call(cmd, shell=True)    # Like on the master; not elegant, but effective
                        sys.exit()  # Should never make it here, but just in case

                    print "Got Msg #{0} | {1} dBm | {2} ft".format(in_dict["value"], in_dict["extras"]["power"], in_dict["extras"]["dist_ft"])
                    if num_rcvd == 0:
                        cutoff = time.time() + TIMEOUT - PACKET_DELAY * (PACKETS_PER - int(in_dict["value"]))

                    rcvd_arr[int(in_dict["value"])-1] = True
                    num_rcvd += 1

            if float(sum(rcvd_arr)) / PACKETS_PER >= THRESHOLD:
                LOG.info("Burst ({0}/{1}) -- OK".format(num_rcvd,PACKETS_PER))

            elif not num_rcvd == 0:    # No point printing a fail if no data was ever received..
                LOG.info("Burst ({0}/{1}) -- FAILED!".format(num_rcvd,PACKETS_PER))

            if not num_rcvd == 0:    # If we got data, record it in the log file
                fptr.write("{0},{1},{2},{3}\n".format(in_dict["extras"]["power"],in_dict["extras"]["dist_ft"],num_rcvd,PACKETS_PER))
                fptr.close()
    LOG.debug("Unable to launch xcV2Xrsu!")
    sys.exit()

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
