#!/usr/bin/python

# $Rev:: 316           $
# $Author:: mlgantra   $
# $Date:: 2015-05-19 1#$
#
# openXC-modem led command handler

'''
    OpenXC-Modem has 5 LEDs where 4 are software controllable via 
      /sys/class/leds pio and one is via AT# command

    D14: GSM status - Special AT# command handler
    D13: WiFi status
    D12: GPS status
    D11: BlueTooth status 
    D10: Battery Power status
'''

import subprocess
import time
from xc_common import *
import xc_ser

led_state = Enum(['OFF', 'ON', 'BLINK0', 'BLINK1'])


class gsmLed:
    def __init__(self, name, debug = 0):
        self.name = name
        self.debug = debug
        if self.debug:
            print (self.name + " init")
        self.gsm_ser = xcmodem_ser.xcModemSer('/dev/ttyACM3', debug = 0)
        self.gsm_ser.send('AT#GPIO=1,0,2\r')
        self.off()

    def on(self):
        if self.debug:
            print (self.name + " on")
        self.gsm_ser.send('AT#SLED=1\r')

    def off(self):
        if self.debug:
            print (self.name + " off")
        self.gsm_ser.send('AT#SLED=0\r')

    def blink(self):
        if self.debug:
            print (self.name + " blink")
        self.gsm_ser.send('AT#SLED=3,1,2\r')

    def default(self):
        if self.debug:
            print (self.name + " default")
        self.gsm_ser.send('AT#SLED=2\r')


class xcModemLed:
    LED_PIO = '/sys/class/leds'

    def __init__(self, name, pdir, debug=0):
        self.name = name
        self.debug = debug
        if self.debug:
            print (self.name + " init")
        self.pdir = "%s/%s" % (xcModemLed.LED_PIO, pdir)
        self.state = led_state.ON    # force off
        self.off()

    def on(self):
        if self.debug:
            print (self.name + " on")
        if self.state == led_state.ON:
            return
        try:
            subprocess.call("echo 1 > %s/brightness" % self.pdir, shell=True)
            subprocess.call("echo 'default-on' > %s/trigger" % self.pdir, shell=True)
        except OSError as e:
            LOG.error("%s fail to access %s" % (self.name, self.pdir))
            pass
        else:
            self.state = led_state.ON

    def off(self):
        if self.debug:
            print (self.name + " off")
        if self.state == led_state.OFF:
            return
        try:
            subprocess.call("echo 0 > %s/brightness" % self.pdir, shell=True)
        except OSError as e:
            LOG.error("%s fail to access %s" % (self.name, self.pdir))
            pass
        else:
            self.state = led_state.OFF

    def blink(self, mode = 0):
        if not mode:     
            state = led_state.BLINK0
            trigger = 'heartbeat'
            info = ' blink mode 0'
        else:
            state = led_state.BLINK1
            trigger = 'timer'
            info = ' blink mode 1'
        if self.debug:
            print (self.name + info)
        if self.state == state:
            return
        try:
            subprocess.call("echo 1 > %s/brightness" % self.pdir, shell=True)
            subprocess.call("echo %s > %s/trigger" % (trigger, self.pdir), shell=True)
        except OSError as e:
            LOG.error("%s fail to access %s" % (self.name, self.pdir))
            pass
        else:
            self.state = state

# Only for V2X and RSU. Modem doesn't change.
# wifi use for dsrc_led.
# gps use for wifi_led

def all_leds(color = 0):
    pathid = (boardid_inquiry() > 0)    # LED path change after EVT board
    leds = []
    if boardid_inquiry() == 1:
        wifi_led = xcModemLed('wifi_led', led_path['wifi'][pathid])
        leds.append(wifi_led)
	gps_led = xcModemLed('gps_led', led_path['gps'][pathid])
	leds.append(gps_led)
    else:
        dsrc_led = xcModemLed('dsrc_led', led_path['wifi'][pathid])
        leds.append(dsrc_led)
        wifi_led = xcModemLed('wifi_led', led_path['gps'][pathid])
        leds.append(wifi_led)
    if pathid:
        gsm_led = xcModemLed('gsm_led', led_path['gsm'][pathid])
    else:
        gsm_led = gsmLed('gsm_led')
    leds.append(gsm_led)
    bt_led = xcModemLed('bt_led', led_path['bt'][pathid])
    leds.append(bt_led)
    bat_led_grn = xcModemLed('bat_led_grn', led_path['bat_grn'][pathid])
    leds.append(bat_led_grn)
    bat_led_red = xcModemLed('bat_led_red', led_path['bat_red'][pathid])
    leds.append(bat_led_red)

    for led in leds:
       if color == 1:      # on
           led.on()
       elif color == 2:    # fast blink
           led.blink()
       elif color == 3:    # slow blink
           led.blink(1)
       else:
           led.off()

def led_test():
    pathid = (boardid_inquiry(1) > 0)   # LED path change after EVT board
    if boardid_inquiry() == 1:
        wifi_led = xcModemLed('wifi_led', led_path['wifi'][pathid], debug=1)
        gps_led = xcModemLed('gps_led', led_path['gps'][pathid], debug=1)
    else:
        dsrc_led = xcModemLed('dsrc_led', led_path['wifi'][pathid], debug=1)
        wifi_led = xcModemLed('wifi_led', led_path['gps'][pathid], debug=1)
    if pathid:
        gsm_led = xcModemLed('gsm_led', led_path['gsm'][pathid], debug=1)
    else:
        gsm_led = gsmLed('gsm_led', debug=1)
    bt_led = xcModemLed('bt_led', led_path['bt'][pathid], debug=1)
    bat_led_grn = xcModemLed('bat_led_grn', led_path['bat_grn'][pathid], debug=1)
    bat_led_red = xcModemLed('bat_led_red', led_path['bat_red'][pathid], debug=1)

    # start with all off from init
    time.sleep(1.0)

    # all on
    if boardid_inquiry() > 1:
        dsrc_led.on()
        time.sleep(0.5)
    wifi_led.on()
    time.sleep(0.5)
    if boardid_inquiry() == 1:
        gps_led.on()
        time.sleep(0.5)
    gsm_led.on()
    time.sleep(0.5)
    bt_led.on()
    time.sleep(0.5)
    bat_led_grn.on()
    time.sleep(0.5)
    bat_led_grn.off()
    bat_led_red.on()
    time.sleep(0.5)
    bat_led_grn.on()
    time.sleep(2)

    # all off
    if boardid_inquiry() > 1:
        dsrc_led.off()
        time.sleep(0.5)
    wifi_led.off()
    time.sleep(0.5)
    if boardid_inquiry() == 1:
        gps_led.off()
        time.sleep(0.5)
    gsm_led.off()
    time.sleep(0.5)
    bt_led.off()
    time.sleep(0.5)
    bat_led_grn.off()
    time.sleep(0.5)
    bat_led_red.off()
    time.sleep(1)

    # all blink mode 0
    if boardid_inquiry() > 1:
        dsrc_led.blink()
    wifi_led.blink()
    if boardid_inquiry() == 1:
        gps_led.blink()
    gsm_led.blink()
    bt_led.blink()
    bat_led_grn.blink()
    time.sleep(3)
    bat_led_grn.off()
    bat_led_red.blink()
    time.sleep(3)
    bat_led_red.off()
    bat_led_grn.blink()
    bat_led_red.blink()
    time.sleep(3)
    # all blink mode 1
    if boardid_inquiry() > 1:
        dsrc_led.blink(1)
    wifi_led.blink(1)
    if boardid_inquiry() == 1:
        gps_led.blink(1)
    gsm_led.blink(1)
    bt_led.blink(1)
    bat_led_red.off()
    bat_led_grn.blink(1)
    time.sleep(3)
    bat_led_grn.off()
    bat_led_red.blink(1)
    time.sleep(3)
    bat_led_red.off()
    bat_led_grn.blink(1)
    bat_led_red.blink(1)
    time.sleep(3)

    # all off
    if boardid_inquiry() > 1:
        dsrc_led.off()
    wifi_led.off()
    if boardid_inquiry() == 1:
        gps_led.off()
    gsm_led.off()
    bt_led.off()
    bat_led_grn.off()
    bat_led_red.off()

if __name__ == '__main__':
    led_test()

