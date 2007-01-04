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
from xc_rsu_common import *
import xc_ver

logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('xcv2x')

try: 
    import bluetooth
except ImportError:
    LOG.debug("pybluez library not installed, can't use bluetooth interface")
    bluetooth = None

msg_count = 500
vid_msg = '{"name": "vehicle_id", "value": "Connected" }'


def main(sdebug = 0, debug = 0):
    first = 1
    attempt = 1
    threads = []
    restart = 0
    tdata = ""
    sdata = ""
    count = 0
    adv_count = 0

    #------------------------------------------------------------
    # update openxc_vi_enable to current setting in xc.conf file
    #------------------------------------------------------------

    LOG.info("OpenXC-V2X Embedded Software - Rev %s" % xc_ver.get_version())

    myhost = os.uname()[1]
    LOG.info(myhost)

    #---------------------------------------#
    #   Clean up Mobile App Queue           #
    #---------------------------------------#
    if (not mb_out_queue.empty()):
        dump=mb_out_queue.get()

    #---------------------------------------
    #   check the current configuration type
    #---------------------------------------
    config_mode = boardmode_inquiry()

    #---------------------------------------
    #   Start VI interface
    #---------------------------------------
    pairing_registration()
    vi_cleanup()
    vi_dev = xcModemVi(port_dict['vi_app']['port'], vi_in_queue, vi_out_queue, sdebug, debug)
    vi_dev.file_discovery('xc.conf')     
    LOG.info("OPENXC_VI_ENABLE= %d" % conf_options['openxc_vi_enable']) 
    
	#------------------------------
    #   ensure that  VI is running
    #------------------------------
    if (conf_options['openxc_vi_enable'] == 1) or (config_mode == 3):  
      vi_status = vi_dev.vi_main(); 
      while ( not vi_status)and (attempt < MAX_BRING_UP_ATTEMPT):
         time.sleep(float(conf_options['openxc_vi_discovery_interval']))
         attempt += 1
         vi_status = vi_dev.vi_main() 
    if (conf_options['openxc_vi_enable'] == 1) or (config_mode == 3):
      if (not vi_status):
        LOG.debug("vi_app max out %d attempts" % MAX_BRING_UP_ATTEMPT)
        sys.exit()
    else:
	vi_status = 0

    #---------------------------------------
    # RSU integration if mode = 2 or 3
    #---------------------------------------
    if (config_mode == 2) or (config_mode == 3):
      xcV2Xrsu_dev = xcV2Xrsu('v2x_2_rsu',port_dict['xcV2Xrsu_tx']['port'],port_dict['xcV2Xrsu_rx']['port'], xcV2Xrsu_in_queue, xcV2Xrsu_out_queue, sdebug, debug)

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


    #----------------------------------------------------------
    # Main Loop. Run if Both the VI and RSU (if needed are up)
    #----------------------------------------------------------
    while True:
        if (vi_status) or (conf_options['openxc_vi_enable'] == 0):
            if first:
                first = 0
                LOG.info("App Tasks ...")

                #---------------------------------------------
                # start Android/Mobil App thread if mode is 2
                #---------------------------------------------
                if (config_mode == 2):
                    if port_dict['mb_app']['enable']:
                       LOG.info("Starting Mobile App...")
                       thread = appThread('mb_app', port_dict['mb_app']['port'], mb_in_queue, mb_out_queue, mb_passthru_queue, passQ)
                       thread.start()
                       threads.append(thread)

            while (not exit_flag['vi_app']) :
                  count = count + 1
                  #-------------------------------
                  # check if there is any data from RSU. If 
                  # so then send it to mobile
                  #-------------------------------
                  if ((config_mode == 2) or (config_mode == 3)):
                    if (not xcV2Xrsu_in_queue.empty()):
                      sdata = sdata + xcV2Xrsu_in_queue.get().replace("{}","").strip(chr(0))     

                      if (len(sdata) > 200):
                       xcV2Xrsu_data = cleanup_json(sdata)
                       if (config_mode == 2):
                        xcV2Xrsu_data = filter_msg(xcV2Xrsu_data,myhost)
                       sdata = ""
                       if (len(xcV2Xrsu_data) >  0):
                         LOG.info("-------------------------------------") 
                         LOG.info("Recd data [[ %s ]]" % xcV2Xrsu_data)
                         LOG.info("-------------------------------------")
                         #--------------------
                         # write to mobile device if operational 
                         #--------------------
                         if modem_state['mb_app'] == app_state.OPERATION:
                            if ((not vi_bypass['mb_app']) and (mb_status['ready'])):
                               mb_out_queue.put(xcV2Xrsu_data)
                         #--------------------
                         # write to modem device if operational 
                         #--------------------
                         if (conf_options['openxc_vi_enable']) or (config_mode == 3):
                          if not vi_bypass['modem_app']:
                             vi_out_queue.put(xcV2Xrsu_data)
                         #--------------------
                         # write to xcV2Xrsu log
                         #--------------------
                         xcV2Xrsu_dev.trace_raw_lock.acquire()
                         if xcV2Xrsu_dev.trace_enable:
                          if xcV2Xrsu_dev.fp:
                            new_xcV2Xrsu_data = xcV2Xrsu_dev.xcV2Xrsu_timestamp(xcV2Xrsu_data)
                            xcV2Xrsu_dev.fp.write(new_xcV2Xrsu_data)
                            sdata = ""
                          else:
                            LOG.info("RSU log file not available")
                         xcV2Xrsu_dev.trace_raw_lock.release()

                    if (count == msg_count): 
                       count = 0 
	      	       adv_count += 1
                       v_msg = vid_msg.replace("vehicle_id", myhost);
                       v_msg = v_msg.replace("Connected", str(adv_count));
                       LOG.info ("----------------------------------------")
                       LOG.info ("Transmitting :  [[ %s ]]" % v_msg) 
                       LOG.info ("----------------------------------------")
                       xcV2Xrsu_out_queue.put(v_msg);

		    msleep(1)
          #-------------------------------
          # continue with the vi then
          #-------------------------------
		  if (conf_options['openxc_vi_enable']) or (config_mode == 3):
                    if not vi_in_queue.empty():
                      tdata = tdata + vi_in_queue.get() 
                      if (len(tdata) > 200): 
                        data = cleanup_json(tdata)
                        tdata = ""
                        if not data is None:
                           #----------------------------------
                           # Send the VI data to mobile app is enabled 
                           # and the interface is operational
                           #----------------------------------
                           if modem_state['mb_app'] == app_state.OPERATION:
                              if ((not vi_bypass['mb_app']) and (mb_status['ready'])):
                                 mb_out_queue.put(data)
                           #----------------------------------
                           #Send the VI data to xcV2Xrsu if enabled
                           #----------------------------------
                           if (modem_state['xcV2Xrsu'] == app_state.OPERATION):
                              if ((port_dict['xcV2Xrsu']['enable']) and (not vi_bypass['xcV2Xrsu_app'])):
                                   xcV2Xrsu_out_queue.put(data)
								   
                           #----------------------------------
                           # and dump to trace file
                           #----------------------------------
                           vi_dev.trace_raw_lock.acquire()
                           if vi_dev.fp and vi_dev.trace_enable:
                              new = vi_dev.vi_timestamp(data)
                              vi_dev.fp.write(new+'\n')
                           vi_dev.trace_raw_lock.release()

                      msleep(1)
					  
	if (conf_options['openxc_vi_enable']):
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
            LOG.debug("vi_app max out %d attempts" % MAX_BRING_UP_ATTEMPT)
            break;
        vi_status = vi_dev.vi_main()

    # terminate all threads
    LOG.info("Terminating all threads")
    for k in exit_flag.keys():
        exit_flag[k] = 1

    # Wait for all threads to complete
    LOG.info("Waiting for all threads to join")
    for t in threads:
        t.join()

    LOG.info("Ending xcmodem")
    return restart
            
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
