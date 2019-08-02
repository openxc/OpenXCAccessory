#!/usr/bin/python

import logging
import Queue
import threading
import time
import os.path
import sys
import os

sys.path.append('../common')
from xc_common import *
from xc_vi import *
from xc_app import *
from xc_rsu_common import *
import xc_ver
import xc_json


logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('xcv2x')

try:
    import bluetooth
except ImportError:
    LOG.debug("pybluez library not installed, can't use bluetooth interface")
    bluetooth = None

[MSG_TTL, MSG_HTL] = [3,1]	# Time to live (TTL) & Hops to live (HTL).  Represents maximum time and maximum number of devices a message can propogate through respectively
DSRC_PER_MIN = 60    # The number of DSRC messages to be broadcast each minute
dsrc_delay = float(60/DSRC_PER_MIN)   #Convert the number of messages per minute into the time to wait between packets


def main(sdebug = 0, debug = 0):
    first = 1
    attempt = 1
    threads = []
    restart = 0
    tdata = ""
    sdata = ""
    adv_count = 0
    last_dsrc = 0

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

    if len(sys.argv) == 2:
        if sys.argv[1].isdigit():
            if int(sys.argv[1]) == 0:
                vehicle_type = 0
            if int(sys.argv[1]) == 1:
                vehicle_type = 1
            if int(sys.argv[1]) == 2:
                vehicle_type = 2
        else:
            print "#####################################"
            print "# [BIKE_SENSE] FATAL ERROR          #"
            print "#####################################"
            print "# Invalid argument                  #"
            print "# "+sys.argv[0]+" {vehicle type enum} #"
            print "# Vehicle Types: 1 car, 2 bike      #"
            print "# Example: " + sys.argv[0] + " 1          #"
            print "#####################################"
            os._exit(1)
    else:
        print "#####################################"
        print "# [BIKE_SENSE] FATAL ERROR          #"
        print "#####################################"
        print "# Missing argument                  #"
        print "# "+sys.argv[0]+" {vehicle type enum} #"
        print "# Vehicle Types: 1 car, 2 bike      #"
        print "# Example: " + sys.argv[0] + " 1          #"
        print "#####################################"
        os._exit(1)  
    #vehicle_type = 2 # enum 0 not init, 1 car,2 bike TODO 
    vehicle_list = {}
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
            rdata = ""


            if vehicle_type == 1:
                v2x_transmit = "V2X_vehicle"
                v2x_listen = "V2X_bicycle"
            elif vehicle_type == 2:
                v2x_transmit = "V2X_bicycle"
                v2x_listen = "V2X_vehicle"

            last_received = 0
            while (True) :
                #MOBILE
                try:
                    if (not mb_in_queue.empty()):
                        rdata = rdata + mb_in_queue.get().replace("{}","")
                        if (len(rdata) > 30):
                            print rdata
                            mobile_data = cleanup_json(rdata)   # <- TODO Is this still needed?
                            rdata = ""
                            if len(mobile_data) > 0:
                                msg_dict = xc_json.JSON_msg_decode(mobile_data)
                                if vehicle_type == 0: 
                                    if msg_dict['name'] == 'V2X_vehicle_setup_mode':
                                        vehicle_type = 1
                                    if msg_dict['name'] == 'V2X_bicycle_setup_mode':
                                        vehicle_type = 2
                                    if vehicle_type == 1:
                                        v2x_transmit = "V2X_vehicle"
                                        v2x_listen = "V2X_bicycle"
                                    elif vehicle_type == 2:
                                        v2x_transmit = "V2X_bicycle"
                                        v2x_listen = "V2X_vehicle"
                                    

                                if msg_dict['name'] == v2x_listen + "_see":
                                    LOG.debug("GOT RESPONSE from Phone: " + mobile_data)
                                    #send dsrc
                                    last_dsrc = time.time()
                                    adv_count += 1
                                    message = v2x_listen + "_confirm"
                                    v_msg = xc_json.JSON_msg_encode(myhost, str(adv_count), {"name":message,"value":msg_dict['value'].split('-')[3]}, [xc_json.get_mac(),MSG_TTL,MSG_HTL,0])
                                    xcV2Xrsu_out_queue.put(v_msg);
                                    vehicle_list[msg_dict['value']] = last_received
                except:
                    pass
                            
                        
                #DSRC
                try:
                    if (not xcV2Xrsu_in_queue.empty()):
                        sdata = sdata + xcV2Xrsu_in_queue.get().replace("{}","")
                        #print "sdata: %s" % sdata
                        if (len(sdata) > 200):
                            xcV2Xrsu_data = cleanup_json(sdata)
                            print '[RAW DSRC RECV]' + xcV2Xrsu_data
                            xcV2Xrsu_data = filter_msg(xcV2Xrsu_data,myhost)
                            sdata = ""
                            if (len(xcV2Xrsu_data) >  0):
                                msg_dict = xc_json.JSON_msg_decode(xcV2Xrsu_data)
                                #DSRC RESPONSE HANDLE
                                #check for boradcast
                                last_received = int(msg_dict['value'])
                                if msg_dict['extras']['name'] == v2x_listen + "_broadcast":
                                    if not msg_dict['extras']['value'] in vehicle_list:
                                        phone_message ='{"name":"' + v2x_listen + '_in_range", "value": "' + msg_dict['extras']['value'] + '"}'
                                        mb_out_queue.put(phone_message)
                                        #vehicle_list[msg_dict['extras']['value']] = int(msg_dict['value'])
                                    else:
                                        if vehicle_list[msg_dict['extras']['value']] + 10 < int(msg_dict['value']):
                                            phone_message ='{"name":"' + v2x_listen + '_in_range", "value": "' + msg_dict['extras']['value'] + '"}'
                                            mb_out_queue.put(phone_message)
                                            #vehicle_list[msg_dict['extras']['value']] = int(msg_dict['value'])

                                        else:
                                            vehicle_list[msg_dict['extras']['value']] = int(msg_dict['value'])
                                if msg_dict['extras']['name'] == v2x_transmit + "_confirm":
                                    name = 'OpenXC-VI-V2X-' + msg_dict['extras']['value']
                                    #if name == myhost:
                                    vehicle_list[msg_dict['name']] = int(msg_dict['value'])
                                    phone_message ='{"name":"' + v2x_listen + '_confirm", "value": "' + msg_dict['extras']['value'] + '"}'
                                    mb_out_queue.put(phone_message)
                except:
                    pass




                                #--------------------
                                # write to mobile device if operational
                                #--------------------
                                #mb_out_queue.put(xcV2Xrsu_data)
                                #--------------------
                                # write to modem device if operational
                                #--------------------
                                #vi_out_queue.put(xcV2Xrsu_data)
                if vehicle_type != 0:
                    if (time.time() - last_dsrc >= dsrc_delay):
                        last_dsrc = time.time()
                        adv_count += 1
                        message = v2x_transmit + "_broadcast"
                        v_msg = xc_json.JSON_msg_encode(myhost, str(adv_count), {"name":message,"value":myhost}, [xc_json.get_mac(),MSG_TTL,MSG_HTL,0])
                        xcV2Xrsu_out_queue.put(v_msg);
                        #print "[V2X Transmit]" + v_msg

                msleep(1)
                    #-------------------------------
                    # continue with the vi then
                    #-------------------------------

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
    #parser = argparse.ArgumentParser()
    #parser.add_argument('-v', help='Verbosity Level (-2..2)')
    #args = parser.parse_args()
    #restart = 1;

    if None is None:
        level = 0
    else:
        level = int(args.v)

    if level < -1:
        LOG.setLevel(level=logging.WARN)
    elif level < 0:
        LOG.setLevel(level=logging.INFO)
    main(sdebug = (level>1), debug = (level>0))
