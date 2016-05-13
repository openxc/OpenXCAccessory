#!/usr/bin/python

# $Rev:: 374           $
# $Author:: mlgantra   $
# $Date:: 2015-06-19 1#$
#
# openXC-modem gps command handler

'''
AT$GPSACP response syntax is
    $GPSACP:<UTC>,<latitude>,<longitude>,<hdop>,<altitude>,<fix>,<cog>,<spkm>,<spkn>,<date>,<nsat>
  ie:
    $GPSACP: 002128.000,3725.3475N,12153.8085W,0.75,6.0,3,310.76,0.35,0.19,071114,10
  where
    <UTC>
    hhmmss UTC of Position
        hh (hour) 00 to 23
        mm (minutes) 00 to 59
        ss (seconds) 00 to 59
    <latitude>: (referred to GGA sentence)
    ddmm.mmmm N/S Values:
        dd (degrees) 00 to 90
        mm.mmmm (minutes) 00,0000 to 59.9999
        N/S: North / South
    <longitude>: (referred to GGA sentence)
    dddmm.mmmm E/W Values:
        ddd (degrees) 00 to 180
        mm.mmmm (minutes) 00,0000 to 59.9999
        E/W: East / West
    <hdop>: (referred to GGA sentence)
    x.x Horizontal Dilution of Precision
    <altitude>: (referred to GGA sentence)
    xxxx.x Altitude mean-sea-level (geoid) (meters)
    <fix>: (referred to GSA sentence)
        1 Invalid Fix
        2 2D fix
        3 3D fix
    <cog>: (referred to VTG sentence)
    ddd.mm Course over Ground (degrees, True)
        ddd: 000 to 360 degrees
        mm 00 to 59 minutes
    <spkm>: (referred to VTG sentence)
    xxxx.x Speed over ground (Km/hr)
    <spkn>: (referred to VTG sentence)
    xxxx.x Speed over ground (knots)
    <date>: (referred to RMC sentence)
    ddmmyy Date of Fix
        dd (day) 01 to 31
        mm (month) 01 to 12
        yy (year) 00 to 99 (2000 to 2099)
    <nsat>: (referred to GSV sentence)
    nn Total number of satellites in view
'''

import subprocess
import re
from xc_common import *
import xc_led  
import xc_ser 
from xc_modem_gsm import gsm_csq_inquiry


# Log GPS info into separate rotating file
GPSLOG = logging.getLogger('gps')
GPSLOG.setLevel(logging.INFO)
GPSLOG_FILENAME = "/var/log/xcmodem.gps"
fh = logging.handlers.RotatingFileHandler(GPSLOG_FILENAME, maxBytes=10240, backupCount=5)
fh.setFormatter(logging.Formatter('%(message)s'))
GPSLOG.addHandler(fh)

SEC_PER_MIN = 60
SEC_PER_HOUR = SEC_PER_MIN * 60
SEC_PER_DAY = SEC_PER_HOUR * 24
SEC_PER_MONTH = SEC_PER_DAY * 31
SEC_PER_YEAR = SEC_PER_MONTH * 12


class xcModemGps:
    def __init__(self, name, sdebug = 0, debug = 0):
        self.name = name
        self.debug = debug
        self.ser = xc_ser.xcModemSer('/dev/ttyACM0', sdebug)
        self.save_once = 0
        self.tick_bk = 0

    def parse(self, line, sync):
        gps_string = line.split(':')[1]
        try:
            (utc, lat, lon, hdop, alt, fix, cog, spkm, spkn, date, nsat) = gps_string.split(',')
        except ValueError as e:
            utc = ''
        else:
            utc = re.sub('\W+',"",utc)        # remove white space
            date = re.sub('\W+',"",date)      # remove white space
        stat = True
        if not self.save_once and utc:
            self.ser.cmd_check('AT$GPSR=3\r','OK')    # Hotstart
            self.ser.cmd_check('AT$GPSSAV\r','OK')    # Save config
            self.save_once = 1
        if sync:
            if not utc:
                return (stat, None, None, None, None, None)
            # GPSLOG
            tick = (int(date[2:4])*SEC_PER_MONTH + \
                    int(date[0:2])*SEC_PER_DAY + \
                    int(date[4:6])*SEC_PER_YEAR + \
                    int(utc[0:2])*SEC_PER_HOUR + \
                    int(utc[2:4])*SEC_PER_MIN + \
                    int(utc[4:6])) / int(conf_options['gps_log_interval'])
            if tick != self.tick_bk:
                self.tick_bk = tick
                GPSLOG.info(line)
            if self.debug:
                lstdout = None
                lstderr = None
            else:
                lstdout = subprocess.PIPE
                lstderr = subprocess.PIPE
            cmd = ("date -s '%s/%s/%s %s:%s:%s UTC'" % \
                     (date[2:4], date[0:2], "20"+date[4:6], \
                      utc[0:2], utc[2:4], utc[4:6]))
            # LOG.debug("issuing " + cmd)                  
            stat = not subprocess.call(cmd, shell=True, \
                                       stdout=lstdout, stderr=lstderr)
        return (stat, utc[0:6], lat, lon, alt, date)

    def start(self):
        LOG.debug("poweron start " + self.name)

        self.ser.set_speed('115200','8N1')
        if self.ser.cmd_check('ATE0\r','OK') is not None:
            if self.ser.cmd_check('AT$GPSP?\r','GPSP: 1') is not None:
                return True
            # Turn it on    
            self.ser.send('AT$GPSP=1\r')
        return False

    def inquiry(self, sync):
        r = self.ser.cmd_check('AT$GPSACP\r',  'GPSACP', SERIAL_INTERFACE_TIMEOUT)
        if r is not None:
            line = r.split('\r\n')[1]
            if self.debug:
                LOG.debug(line)
            return self.parse(line, sync)
        LOG.warning("fail to acquire position " + self.name)
        return (0, None, None, None, None, None)

    # Since GPS task already utilize /dev/acm0, use it to monitor GSM signal quality 
    def csq_inquiry(self):
        return gsm_csq_inquiry(self.ser, self.debug)


class gpsThread (threading.Thread):
    GPS_START_DELAY = 1
    # Note: GPSACP request currently last SERIAL_INTERFACE_TIMEOUT secs

    def __init__(self, sdebug = 0, debug = 0):
        threading.Thread.__init__(self)
        self.name = 'gps_app'
        pathid = boardid_inquiry() > 0
        self.led = xc_led.xcModemLed('gps_led', led_path['gps'][pathid])
        self.gps = xcModemGps(self.name, sdebug, debug)

    def run(self):
        LOG.debug("Starting " + self.name)

        modem_state[self.name] = app_state.PENDING
        LOG.info("%s state %s" % (self.name,  modem_state[self.name]))
        exit_flag[self.name] = 0

        while True:
            if self.gps.start():
                modem_state[self.name] = app_state.CONNECTED
                LOG.info("%s state %s" % (self.name,  modem_state[self.name]))
                self.led.on()
                break
            time.sleep(gpsThread.GPS_START_DELAY)   

        while not exit_flag['all_app']:
            status, utc, lat, lon, alt, date = self.gps.inquiry(True)
            if not status:
                state = app_state.CONNECTED
                self.led.on()
            elif utc:
                state = app_state.OPERATION
                self.led.blink()
            else:
                state = app_state.LOCKING
                self.led.blink(1)
            if modem_state[self.name] != state:
                modem_state[self.name] = state
                LOG.info("%s state %s" % (self.name,  modem_state[self.name]))
            gps_dict['utc'] = utc
            gps_dict['lat'] = lat
            gps_dict['lon'] = lon
            gps_dict['alt'] = alt
            gps_dict['date'] = date

            idle_time = 1 - SERIAL_INTERFACE_TIMEOUT 
            if conf_options['gsm_enable']:
               self.gps.csq_inquiry()
               idle_time -= SERIAL_INTERFACE_TIMEOUT   
            time.sleep(idle_time)   


if __name__ == '__main__':
    if boardid_inquiry(1) > 1:    # V2X doesn't support GPS
        LOG.error("V2X doesn't support GPS")
        exit()

    parser = argparse.ArgumentParser()
    parser.add_argument('-v', help='Verbosity Level (0..2)')
    args = parser.parse_args()

    if args.v is None:
        level = 0
    else:
        level = int(args.v)

    t = gpsThread(sdebug = (level>1), debug = (level>0))
    t.start()
    t.join()
