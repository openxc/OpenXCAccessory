#!/usr/bin/python

# $Rev:: 237           $
# $Author:: mlgantra   $
# $Date:: 2015-03-31 1#$
#
# openXC-modem application agents command handlers


import argparse
import json
import time
import re
import sys
import socket

from xc_common import *
import xc_ver

############################
# For MB_APP 
############################
def mb_parse_options(list, v2x):
    # MRC - Use JSON library instead..?
    
    # Utilize argparse for command usage information
    parser = argparse.ArgumentParser(
            description="xc modem interface command handler", prog="xcmodem mb")
    parser.add_argument("command_type", type=str, choices=['command','modem_command', 'V2X_command', 'caravan_msg', 'value'])
    if v2x == 2:
       parser.add_argument("V2X_commands", type=str, choices=['device_id', 'version','diagnostics_enable','diagnostics_disable'])
    else:
       parser.add_argument("modem_commands", type=str, choices=['device_id', 'version','diagnostics_enable','diagnostics_disable'])

    return parser.parse_args(list)
#----------------------------------------------------------------------------

DIAG_SCREEN_UPDATE_INTERVAL = 1.0

#----------------------------------------------------------------------------
def mb_diagnostic_screen(v2x, name, outQ):
    while vi_bypass[name]:
        for l in modem_state.items():
            if not vi_bypass[name]:
                break
            (key, val) = l
            if (v2x == 2) and (key == 'gps_app' or key == 'gsm_app'):       # skip V2X un-support apps
                continue
            tstamp = time.time()
            if (v2x == 2):
               reply = '{"V2X_label":"%s.state","V2X_value":"%s","timestamp":%f}\0' % (key, val, tstamp)
            else:
               reply = '{"modem_label":"%s.state","modem_value":"%s","timestamp":%f}\0' % (key, val, tstamp)
            outQ.put(reply)

        for l in port_mac.items():
            if not vi_bypass[name]:
                break
            (key, val) = l
            tstamp = time.time()
            if (v2x == 2):
              reply = '{"V2X_label":"%s.mac","V2X_value":"%s","timestamp":%f}\0' % (key, val, tstamp)
            else:
              reply = '{"modem_label":"%s.mac","modem_value":"%s","timestamp":%f}\0' % (key, val, tstamp)
            outQ.put(reply)

        if conf_options['gps_enable'] and not (v2x == 2):
            for l in gps_dict.items():
                if not vi_bypass[name]:
                    break
                (key, val) = l
                tstamp = time.time()
                reply = '{"modem_label":"gps.%s","modem_value":"%s","timestamp":%f}\0' % (key, val, tstamp)
                outQ.put(reply)

        if conf_options['gsm_enable'] and not (v2x == 2):
            for l in gsm_dict.items():
                if not vi_bypass[name]:
                    break
                (key, val) = l
                tstamp = time.time()
                reply = '{"modem_label":"gsm.%s","modem_value":"%s","timestamp":%f}\0' % (key, val, tstamp)
                outQ.put(reply)

   
        for l in conf_options.items():
            if not vi_bypass[name]:
                break
            (key, val) = l
            if (v2x==2) and (key == 'gps_enable' or key == 'gsm_enable'): # skip V2X un-support apps
                continue
            if ((not (v2x==2)) and ("chd" in key)): # skip modem un-support apps
                continue
            tstamp = time.time()
            if re.search(r'_interval', key, re.M|re.I) \
                or re.search(r'_duration', key, re.M|re.I) \
                or re.search(r'_size', key, re.M|re.I) :
                if (v2x == 2):
                   reply = '{"V2X_label":"%s","V2X_value":%d,"timestamp":%f}\0' % (key, int(val), tstamp)
                else:
                   reply = '{"modem_label":"%s","modem_value":%d,"timestamp":%f}\0' % (key, int(val), tstamp)
            else:
                if (v2x == 2):
                   reeply = '{"V2X_label":"%s","V2X_value":"%s","timestamp":%f}\0' % (key, val, tstamp)

                else:
                   reply = '{"modem_label":"%s","modem_value":"%s","timestamp":%f}\0' % (key, val, tstamp)
            if (not reply is None):
             outQ.put(reply)
        time.sleep(DIAG_SCREEN_UPDATE_INTERVAL)

#-----------------------------------------------------------------------------
def dummy_mb_vi_commands_handler(v2x, name, stop_event, outQ, cmd):
    bypass_mode = vi_bypass[name]
    vi_bypass[name] = True                  # temparily hold pass-thru mode
    diag_start = False
    if cmd == 'device_id':
        value = 'XYZ' 
    elif cmd == 'version':
        value = '0.1.4' 
    elif cmd == 'diagnostics_enable':
        value = None
    elif cmd == 'diagnostics_disable':
        value = None

   
    if value is not None:
     reply = '{"command_response":"%s","message":"%s","status":false}' % (cmd, value)

    #LOG.info(">>>>Reply value = %s", reply)
#12    outQ.put(reply)
    if cmd == 'device_id':
       mb_status['vi_id_sent'] = True 
    elif cmd == 'version':
       mb_status['vi_version_sent'] = True 
    #LOG.info("#####################################")
    vi_bypass[name] = bypass_mode            # restore pass-thru mode

#-----------------------------------------------------------------------------
def dummy_mb_commands_handler(v2x, name, stop_event, outQ, cmd):
    bypass_mode = vi_bypass[name]
    vi_bypass[name] = True                  # temparily hold pass-thru mode
    diag_start = False
    if cmd == 'device_id':
        value = 'XYZ' 
    elif cmd == 'version':
        value = '0.1.4' 
    elif cmd == 'diagnostics_enable':
        value = None
    elif cmd == 'diagnostics_disable':
        value = None

    if value is not None:
       if v2x == 2:
          reply = '{"modem_command_response":"%s","modem_message":"%s","status":false}' % (cmd, value)
       else:
          reply = '{"V2X_command_response":"%s","V2X_message":"%s","status":false}' % (cmd, value)
    else:
       if v2x == 2:
        reply = '{"modem_command_response":"%s","status":false}' % cmd
       elif v2x == 1:
        reply = '{"V2X_command_response":"%s","status":false}' % cmd
    if cmd == 'device_id':
      if (v2x == 2):
        mb_status['modem_id_sent']= True
      else:
        mb_status['v2x_id_sent']= True
    elif cmd == 'version':
      if (v2x == 2):
        mb_status['modem_version_sent']= True
      else:
        mb_status['v2x_version_sent']= True
    vi_bypass[name] = bypass_mode            # restore pass-thru mode
#---------------------------------------------------------------------------------
def mb_commands_handler(v2x, name, stop_event, outQ, cmd):
    bypass_mode = vi_bypass[name]
    vi_bypass[name] = True                  # temparily hold pass-thru mode
    diag_start = False
    if cmd == 'device_id':
        value = socket.gethostname()
    elif cmd == 'version':
        value = xc_ver.get_version()
    elif cmd == 'diagnostics_enable':
        value = None
        if not bypass_mode:
            diag_start = True
        bypass_mode = True
        mb_status['ready'] = False
    elif cmd == 'diagnostics_disable':
        value = None
        bypass_mode = False                 # turn-off bypass mode
        mb_status['ready'] = True
        if stop_event is not None:
            stop_event.set()                # terminate mb_diagnostic_screen thread
            stop_event = None

    if value is not None:
       if v2x == 2:
          reply = '{"V2X_command_response":"%s","V2X_message":"%s","status":true}\0' % (cmd, value)
       else:
          reply = '{"modem_command_response":"%s","modem_message":"%s","status":true}\0' % (cmd, value)
    else:
       if v2x:
        reply = '{"V2X_command_response":"%s","status":true}\0' % cmd
       else:
        reply = '{"modem_command_response":"%s","status":true}\0' % cmd
       
    outQ.put(reply)

    if (cmd == 'device_id'):
     if (v2x == 2):
       mb_status['v2x_id_sent'] = True;
     else:
       mb_status['modem_id_sent'] = True;

    elif (cmd == 'version'):
     if (v2x == 2):
       mb_status['v2x_version_sent'] = True;
     else:
       mb_status['modem_version_sent'] = True;
     

    vi_bypass[name] = bypass_mode            # restore pass-thru mode
    if diag_start:
        thread, stop_event = loop_timer(None, mb_diagnostic_screen, v2x, name, outQ)

#----------------------------------------------------------------------------------------
def combined_command_handler(list, str):
    # To handle combined command in one line
    l = re.search('}\W*{', str)
    if l:
        list.append(str[:l.start()+1])
        combined_command_handler(list, str[l.end()-1:])
    else:
        list.append(str)

#----------------------------------------------------------------------------------------
def empty_queue(Q):
    while not Q.empty():
          data = Q.get()

#----------------------------------------------------------------------------------------

def mb_process_data(v2x, name, outQ, passQ, data):
    # Limitation: don't handle partial command string
    stop_event = None
    #LOG.info("Command in mb_proces_data = %s" % data)
    command_list = []
    combined_command_handler(command_list, data)    # break into single commands list
    for line in command_list:
        #LOG.info("The parsed command = %s" % line)
        try:
            list = re.sub('\W+'," ", line).split()
            arguments = mb_parse_options(list, v2x)
        except SystemExit:
            LOG.error("Unknown command: " + line)# - Not really an error
            return 0
        else:
            if arguments.command_type == 'command':
                mb_status['vi_id_sent'] = True
                mb_status['vi_version_sent'] = True
                passQ.put(line)
            elif arguments.command_type == 'modem_command': 
                 mb_status['ready'] = False
                 if v2x == 1:
                    stop_event = mb_commands_handler(v2x, name, stop_event, outQ, arguments.modem_commands)
                 elif v2x == 2:
                    #LOG.info("modem commands are not allowed on V2X, ignorning")
                    dummy_mb_commands_handler(v2x, name, stop_event, outQ, arguments.V2X_commands)

            elif arguments.command_type == 'V2X_command': 
                 if v2x == 2:
		    stop_event = mb_commands_handler(v2x, name, stop_event, outQ, arguments.V2X_commands)
                 elif v2x == 1:
                    #LOG.info("V2X commands are not allowed on Modem, ignorning")
                    dummy_mb_commands_handler(v2x, name, stop_event, outQ, arguments.modem_commands)

    return 0

############################
# For PC_APP 
############################
def pc_process_data(v2x, name, outQ, passQ, line):
    # TBD
    pass


############################
# Unit test
############################
def test_drain(queue):
    while True:
        while not queue.empty():
            data = queue.get()
            #print("send: [%s]" % data)

def test_main():
    v2x = boardid_inquiry(1) == 2
    outQ = Queue.Queue()
    passQ = Queue.Queue()
    thread1, stop_out = loop_timer(None, test_drain, outQ)           # thread to drain outQ
    thread2, stop_pass = loop_timer(None, test_drain, passQ)         # thread to drain passQ

    name = 'mb_app'
    mb_process_data(v2x, name, outQ, passQ,'{"command":"version"}{"command":"device_id"}')
    mb_process_data(v2x, name, outQ, passQ,'{"abc":"device_id"}')
    mb_process_data(v2x, name, outQ, passQ,'{"modem_command":"device_id"}')
    mb_process_data(v2x, name, outQ, passQ,'{"command":"device_id"}')
    mb_process_data(v2x, name, outQ, passQ,'{"modem_command":"version"}')
    mb_process_data(v2x, name, outQ, passQ,'{"modem_command":"diagnostics_enable"}')
    mb_process_data(v2x, name, outQ, passQ,'{"modem_label":"accelerator_pedal_position","modem_value":0,"timestamp":1364323939.012000}')
    time.sleep(5)
    mb_process_data(v2x, name, outQ, passQ,'{"modem_command":"diagnostics_disable"}')
    mb_process_data(v2x, name, outQ, passQ,'{"command":"version"}')
    mb_process_data(v2x, name, outQ, passQ,'{"modem_command":"diagnostics_enable"}')
    mb_process_data(v2x, name, outQ, passQ,'{"modem_command":"diagnostics_disable"}')

    stop_out.set()
    stop_pass.set()
    time.sleep(1)

if __name__ == '__main__':
    test_main()
