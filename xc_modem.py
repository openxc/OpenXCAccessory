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

sys.path.append('../common')

from xc_common import *
from xc_vi import *
from xc_app import *
import xc_ver

XCMODEM_CONFIG_FILE = 'xc.conf'

logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('xcmodem')

try: 
    import bluetooth
except ImportError:
    LOG.debug("pybluez library not installed, can't use bluetooth interface")
    bluetooth = None


def main(sdebug = 0, debug = 0):
    first = 1
    attempt = 1
    threads = []
    tdata = ""


    LOG.info("OpenXCModem Embedded Software - Rev %s" % xc_ver.get_version())
    #---------------------------------------
    #   check the current configuration type
    #---------------------------------------
    
    config_mode = boardmode_inquiry()  
    LOG.info("The config mode in board id file is %d" % boardmode_inquiry())

    pairing_registration()
    vi_cleanup()
    vi_dev = xcModemVi(port_dict['vi_app']['port'], vi_in_queue, vi_out_queue, sdebug, debug)
    vi_dev.file_discovery('xc.conf')
    vi_status = 0


    #-----------------------------------
    # ensure that VI is running
    #-----------------------------------
    vi_status = vi_dev.vi_main();
    while ( not vi_status)and (attempt < MAX_BRING_UP_ATTEMPT) and (conf_options['openxc_vi_enable']):
       time.sleep(float(conf_options['openxc_vi_discovery_interval']))
       attempt += 1
       vi_status = vi_dev.vi_main()
    if (conf_options['openxc_vi_enable'] == 1):
      if (not vi_status):
        LOG.debug("vi_app max out %d attempts" % MAX_BRING_UP_ATTEMPT)
        sys.exit()

    while True:
        if (vi_status) or (conf_options['openxc_vi_enable'] == 0):
            if first:
                first = 0
                LOG.info("App Tasks ...")
                # PC App thread
                thread, stop_pass = loop_timer(None, test_drain, passQ)
                threads.append(thread)
      
                if port_dict['pc_app']['enable']:
                    thread = appThread('pc_app', port_dict['pc_app']['port'], pc_in_queue, pc_out_queue, vi_out_queue)
                    thread.start()
                    threads.append(thread)

                # Android/Mobil App thread
                if port_dict['mb_app']['enable']:
                    LOG.info("Starting mb_app")
                    thread = appThread('mb_app', port_dict['mb_app']['port'], mb_in_queue, mb_out_queue, mb_passthru_queue, passQ)
                    thread.start()
                    threads.append(thread)

                # Modem-to-v2x Thread (start only if in config mode 3 
                if (config_mode == 3):
                  LOG.info("Starting m_2_v2x thread")
                  if port_dict['m_2_v2x']['enable']:
                    thread = appSockThread('m_2_v2x', port_dict['m_2_v2x']['port'], modem_in_queue, modem_out_queue, modem_vi_out_queue)
                    thread.start()
                    threads.append(thread)

                # GPS thread
                if conf_options['gps_enable']:
                    sys.path.append('../modem')                # GPS is only supported in modem
                    import xc_modem_gps
                    thread = xc_modem_gps.gpsThread(sdebug, debug)
                    thread.start()
                    threads.append(thread)

            while not exit_flag['vi_app']:
                if not vi_in_queue.empty():
                    tdata = tdata + vi_in_queue.get()
                    if (len(tdata) > 200):
                      data = cleanup_json(tdata)
                      tdata = ""
                      if not data is None:
                        if modem_state['pc_app'] == app_state.OPERATION:
                           if not vi_bypass['pc_app']:
                              pc_out_queue.put(data)
                        if modem_state['mb_app'] == app_state.OPERATION:
                           if not vi_bypass['mb_app'] and mb_status['ready']:
                              mb_out_queue.put(data)
                        if modem_state['m_2_v2x'] == app_state.OPERATION:
                              modem_out_queue.put(data)
                        vi_dev.trace_raw_lock.acquire()
                        if vi_dev.fp and vi_dev.trace_enable:
                           new = vi_dev.vi_timestamp(data)
                           vi_dev.fp.write(new)
                        vi_dev.trace_raw_lock.release()
                if (config_mode == 3):
                    if (not modem_in_queue.empty()):
                       vi_dev.v2x_trace_raw_lock.acquire()
                       if vi_dev.v2x_fp and vi_dev.v2x_trace_enable:
			  data = modem_in_queue.get()
                          if modem_state['mb_app'] == app_state.OPERATION:
                           if not vi_bypass['mb_app'] and mb_status['ready']:
                              mb_out_queue.put(data)
                          LOG.info(data)
                          new = vi_dev.vi_timestamp(data)
                          vi_dev.v2x_fp.write(new)
                       vi_dev.v2x_trace_raw_lock.release()
                else:
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
            LOG.debug("vi_app max out %d attempts in xc_modem.py" % MAX_BRING_UP_ATTEMPT)
            break;

    # terminate all threads
    LOG.info("Terminating all threads")
    for k in exit_flag.keys():
        exit_flag[k] = 1

    # Wait for all threads to complete
    for t in threads:
        t.join()

    LOG.info("Ending xcmodem")
            
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', help='Verbosity Level (-2..2)')
    args = parser.parse_args()

    if args.v is None:
        level = 0
    else:
        level = int(args.v)

    if level < -1:
        LOG.setLevel(level=logging.WARN)
    elif level < 0:
        LOG.setLevel(level=logging.INFO)
    main(sdebug = (level>1), debug = (level>0))
