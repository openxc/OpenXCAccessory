#!/usr/bin/python

# $Rev:: 244           $
# $Author:: mlgantra   $
# $Date:: 2015-04-03 1#$
#
# openXC-modem main function

import logging
import Queue
import threading
import time
import os.path
import sys
#import argparse

sys.path.append('../common')
from xc_common import *
from xc_vi import *
from xc_app import *
from xc_rsu_common import *
import xc_ver
from rsu_fn import *
from cleanup import *

logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('xcmodem')


def main(sdebug = 0, debug = 0):
    first = 1
    attempt = 1
    threads = []
    restart = 0
    rsu_dev = None
    myhost = os.uname()[1]


    LOG.info("OpenXC-RSU Embedded Software - Rev %s" % xc_ver.get_version())

    #---------------------------------------
    #   check the current configuration type
    #---------------------------------------
    config_mode = boardmode_inquiry() 
    LOG.info("Config mode = %s " % config_mode)

    #---------------------------------------
    # RSU integration code
    #---------------------------------------
    #if (config_mode == 3) or (config_mode == 5):
    if (config_mode == 2) or (config_mode == 3):
      rsu_dev = xcV2Xrsu('rsu_2_v2x', port_dict['xcV2Xrsu_tx']['port'],port_dict['xcV2Xrsu_rx']['port'], xcV2Xrsu_in_queue, xcV2Xrsu_out_queue, sdebug, debug)

      #------------------------------
      # Create a Garage instance
      #------------------------------
      garage1 =  ParkingGarage(myhost + "_Garage1 ", "Garage1", 1000, -121.0, 30.0, 10)


    #----------------------------------------
    # RSU is up. Run the main loop
    #----------------------------------------
    while True:
        if (rsu_dev.xcV2Xrsu_main()):
            while not exit_flag['rsu_2_v2x']:
                data = garage1.get_status()
                LOG.info("---------------------------------------------------")
                LOG.info("send:" + data.replace("{}",""))
                LOG.info("---------------------------------------------------")
                if (port_dict['xcV2Xrsu_tx']['enable']):
                 xcV2Xrsu_out_queue.put(data)
                count = 0
                while (count < 100) and (not xcV2Xrsu_in_queue.empty()):
                    tdata = rsu_dev.inQ.get()
                    data = filter_msg(tdata,myhost)
                    if (len(data) > 0):
                     print("rec [%s]" % data)
                    new = rsu_dev.xcV2Xrsu_timestamp(data)
                    rsu_dev.trace_raw_lock.acquire()
                    if rsu_dev.fp and rsu_dev.trace_enable:
                        rsu_dev.fp.write(new)
                    rsu_dev.trace_raw_lock.release()
                    count = count + 1
                time.sleep(conf_options['openxc_xcV2Xrsu_msg_send_interval'])

        modem_state['xcV2Xrsu'] = xcV2Xrsu_state.LOST
        rsu_dev.lost_cnt += 1
        LOG.info("v2x_2_rsu state %s %d time" % (modem_state['xcV2Xrsu'], rsu_dev.lost_cnt))
        rsu_dev.xcV2Xrsu_exit()

        if exit_flag['all_app']:
            LOG.debug("Ending all_app")
            break;
        time.sleep(10.0)
        attempt += 1
        if (attempt > MAX_BRING_UP_ATTEMPT):
            LOG.debug("v2x_2_rsu max out %d attempts" % MAX_BRING_UP_ATTEMPT)
            break;

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
