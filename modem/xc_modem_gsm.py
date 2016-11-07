#!/usr/bin/python

# $Rev:: 393           $
# $Author:: mlgantra   $
# $Date:: 2015-06-24 1#$
#
# openXC-modem gsm application

import sys
sys.path.append('../common')
import argparse
import subprocess
import time
import re
import os
from xc_common import *
from xc_led import gsmLed, xcModemLed
import xc_ser


# Standalone function so it can be utilized with serial interface in other tasks
def gsm_csq_inquiry(ser, debug = 0):
    from math import pow

    rsp = ser.cmd_check('AT+CSQ\r',  'CSQ', SERIAL_INTERFACE_TIMEOUT)
    if rsp is not None:
        # +CSQ: 31, 5
        # RSSI = [0..31|99] for [-113..-51 dBm|Unknown]
        # BER  = [0..7|99] for [0.0..12.8 %] < BER < [0.2..35.6 %|Unknown]
        lst = re.sub('\W+'," ",rsp.split()[1]).split()
        if len(lst) == 2:
            val = int(lst[0])
            if val != 99:
                rssi = val*2 - 113
                gsm_dict['rssi'] = rssi
            else:
                gsm_dict['rssi'] = 'UNKNOWN'
            val =  int(lst[1])
            if val != 99:
                ber =  pow(2,val)/10
                gsm_dict['ber'] = ber
            else:
                gsm_dict['ber'] = 'UNKNOWN'
            if debug:
                LOG.debug("RSSI = %s" % gsm_dict['rssi'])
                LOG.debug("BER  > %s%%" % gsm_dict['ber'])
            return True
    LOG.warn("fail to inquire signal quality")
    gsm_dict['rssi'] = None
    gsm_dict['ber'] = None
    return False


class xcModemGsm:
    MAX_ATTEMPT = 3

    def __init__(self, sdebug = 0, debug = 0, tear_off = 0):
        self.name = 'gsm_app'
        self.debug = debug
        self.sdebug = sdebug
        if self.debug:
            print (self.name + " init")
        self.gsm_ser = xc_ser.xcModemSer('/dev/ttyACM3', self.sdebug)
        self.gsm_ser.set_speed('115200','8N1')
        self.led_ctl = boardid_inquiry() > 0
        if self.led_ctl:
            self.gsm_led = xcModemLed('gsm_led', led_path['gsm'][self.led_ctl])
            self.gsm_led.off()
        else:
            self.gsm_led = gsmLed('gsm_led')
            self.gsm_led.default()
        self.start_once = 0
        self.tear_off = tear_off
        self.csq_thread = None
        modem_state[self.name] = app_state.IDLE

    def clk_sync(self):
        # clock sync with cellular timestamp
        if self.debug:
            lstdout = None
            lstderr = None
        else:
            lstdout = subprocess.PIPE
            lstderr = subprocess.PIPE

        # setup UTC mode
        if self.gsm_ser.cmd_check('AT#CCLKMODE=1\r','OK') is not None:
            rsp = self.gsm_ser.cmd_check('AT+CCLK?\r','CCLK')
            if rsp is not None:
                # +CCLK: "15/01/16,14:13:46-32"
                lst = re.sub('\W+'," ",rsp.split()[1]).split()
                cmd = ("date -s '%s/%s/%s %s:%s:%s UTC'" % \
                       (lst[1], lst[2], "20"+lst[0], lst[3], lst[4], lst[5]))
                # LOG.debug("issuing " + cmd)
                subprocess.call(cmd, shell=True, stdout=lstdout, stderr=lstderr)

    def prep(self, apn):
        if self.led_ctl:
            self.gsm_led.on()
        # only prep once
        if modem_state[self.name] == app_state.PENDING:
            LOG.debug("Skip preparing " + self.name)
            return True

        LOG.debug("Preparing " + self.name)

        if self.debug:
            lstdout = None
            lstderr = None
        else:
            lstdout = subprocess.PIPE
            lstderr = subprocess.PIPE

        # clean up lingering pppd process if exist
        subprocess.call('killall -q pppd', shell=True, \
                        stdout=lstdout, stderr=lstderr)

        # Since main gsm channel will be locked during PPP connection,
        # alternative channel (which is also used by GPS) is needed for signal quality monitor
        # Hence, signal quality monitor thread should be started only if gps is not enable;
        # otherwise, GPS task will monitor signal qualilty
        if not conf_options['gps_enable']:
            self.gsm_ser1 = xc_ser.xcModemSer('/dev/ttyACM0', self.sdebug)
            self.gsm_ser1.set_speed('115200','8N1')
            self.gsm_ser1.cmd_check('ATE0\r','OK')
            self.csq_thread, self.stop_csq = loop_timer(1 - SERIAL_INTERFACE_TIMEOUT, \
                                                        gsm_csq_inquiry, self.gsm_ser1, self.debug)

        if apn is None:
            apn = conf_options['web_scp_apn']

        attempt = 1
        cmd = 'AT+CGDCONT=1,"IP","%s"\r' % apn
        while (attempt <= xcModemGsm.MAX_ATTEMPT):
            if self.gsm_ser.cmd_check('ATE0\r','OK') is not None:
                if self.gsm_ser.cmd_check('AT#QSS?\r','QSS: 2') is None:
                    # default QSS mode to 2 per Telit's suggestion
                    self.gsm_ser.cmd_check('AT#QSS=2\r','OK')   # default to mode 2
                    self.gsm_ser.cmd_check('AT&W0\r','OK')      # store into profile0
                    self.gsm_ser.cmd_check('AT&P0\r','OK')      # full profile0 reset in next boot
                if self.gsm_ser.cmd_check('AT#QSS?\r','QSS: 2,0') is not None:
                    LOG.error("SIM not inserted " + self.name)
                    if self.led_ctl:
                        self.gsm_led.blink(1)    # different blink mode
                    return False
                if self.gsm_ser.cmd_check(cmd, 'OK') is not None:
                    if self.gsm_ser.cmd_check('AT#SGACT?\r','SGACT: 1,0') is not None:
                        break
                    elif self.gsm_ser.cmd_check('AT#SGACT=1,0\r','OK') is not None:
                        if self.gsm_ser.cmd_check('AT#SGACT?\r','SGACT: 1,0') is not None:
                            break;
            attempt += 1
        if attempt > xcModemGsm.MAX_ATTEMPT:
            LOG.error("fail to prepare " + self.name)
            return False
        else:
            # For GSM 850Mhz + PCS 1900Mhz
            self.gsm_ser.cmd_check('AT#BND=3,4\r','OK')
            # Telit real-time clock sync; however, it's not guarantee the timestamp is correct
            self.clk_sync()
            modem_state[self.name] = app_state.PENDING
            return True

    def start(self):
        if self.led_ctl:
            self.gsm_led.blink()
        if self.start_once and not self.tear_off:
            LOG.debug("GSM ALREADY UP !!! Skip starting " + self.name)
            modem_state[self.name] = app_state.OPERATION
            if os.path.exists("/var/run/ppp0.pid"):
                return True
            # ppp connection has been lost
            LOG.error("Lost ppp connection " + self.name)
            modem_state[self.name] = app_state.LOST
            if self.led_ctl:
                self.gsm_led.off()
            return False

        LOG.debug("Starting " + self.name)
        if modem_state[self.name] != app_state.PENDING:
            LOG.error("not yet ready to start " + self.name)
            return False

        if self.debug:
            lstdout = None
            lstderr = None
        else:
            lstdout = subprocess.PIPE
            lstderr = subprocess.PIPE

        # invoke pppd daemon
        subprocess.call('pppd file /etc/pppd_script &', shell=True, \
                        stdout=lstdout, stderr=lstderr)
        attempt=1
        while (attempt <= xcModemGsm.MAX_ATTEMPT):
            time.sleep(10.0)
            if not subprocess.call('ifconfig | grep ppp0', shell=True, \
                                   stdout=lstdout, stderr=lstderr):
                if not subprocess.call('route add default ppp0', shell=True, \
                                       stdout=lstdout, stderr=lstderr):
                    modem_state[self.name] = app_state.OPERATION
                    if not self.start_once:
                        # Perform network clock synch then stop it to avoid wasting dataplan
                        subprocess.call('service ntp stop; ntpdate -s time.nist.gov; service ntp start; \
                                         sleep 1; service ntp stop', \
                                        shell = True, stdout=lstdout, stderr=lstderr)
                    self.start_once = True
                    return True
            attempt += 1
        LOG.error("fail to establish " + self.name)
        return False


    def stop(self, force = 0):
        if self.led_ctl:
            self.gsm_led.on()
        if self.start_once and not self.tear_off and not force:
            LOG.debug("Skip ending " + self.name)
            modem_state[self.name] = app_state.PENDING
            return True

        # Tear off ppp connection
        LOG.debug("Ending " + self.name)

        if modem_state[self.name] != app_state.OPERATION and not force:
            LOG.error("not yet ready to stop " + self.name)
            return False

        if self.debug:
            lstdout = None
            lstderr = None
        else:
            lstdout = subprocess.PIPE
            lstderr = subprocess.PIPE

        modem_state[self.name] = app_state.PENDING

        if subprocess.call('killall -q pppd', shell=True, \
                           stdout=lstdout, stderr=lstderr):
            LOG.error("fail to tear off " + self.name)
            modem_state[self.name] = app_state.LOST
            return False
        return True


    def __del__(self):
        LOG.debug("destroy " + self.name)
        if self.csq_thread is not None:
            self.stop_csq.set()
            self.csq_thread.join()


def gsm_test():
    if boardid_inquiry(1) > 1:    # V2X doesn't support GSM
        LOG.error("V2X doesn't support GSM")
        exit()

    parser = argparse.ArgumentParser()
    parser.add_argument('-apn', help='Access Point Name Entry')
    parser.add_argument('-v', help='Verbosity Level (0..2)')
    args = parser.parse_args()

    apn = args.apn
    if args.apn is None:
        apn = conf_options['web_scp_apn']

    if args.v is None:
        level = 0
    else:
        level = int(args.v)

    conf_options['gps_enable'] = 0
    gsm = xcModemGsm(sdebug = (level>1), debug = (level>0))
    fail = 0
    if gsm.prep(apn):
        if gsm.start():
            if subprocess.call('ping -c 3 -I ppp0 www.yahoo.com', shell=True):
                fail = 1
            if gsm.stop(force = 1):
                time.sleep(3)
                if not fail:
                    print "Unit Test Done"
                    return True
    print "Unit Test Fail"
    return False


if __name__ == '__main__':
    gsm_test()
