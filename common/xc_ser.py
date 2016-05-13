#!/usr/bin/python

# $Rev:: 133           $
# $Author:: mlgantra   $
# $Date:: 2015-01-21 1#$
#
# openXC-modem serial utils derived from Telit GPS/GSM SER utils.

#Telit Extensions
#
#Copyright 2012, Telit Communications S.p.A.
#All rights reserved.
#
#Redistribution and use in source and binary forms, with or without 
#modification, are permitted provided that the following conditions 
#are met:
#
#Redistributions of source code must retain the above copyright notice, 
#this list of conditions and the following disclaimer.
#
#Redistributions in binary form must reproduce the above copyright 
#notice, this list of conditions and the following disclaimer in 
#the documentation and/or other materials provided with the distribution.
#
#
#THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS ``AS
#IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
#TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
#PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE REGENTS OR
#CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
#EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
#PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
#PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
#LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
#NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
#SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

import serial
import time
import re
import subprocess
from xc_common import *

class xcModemSer:
    MAX_ATTEMPT = 3
    def __init__(self, dev, debug = 0):
        self.name = dev
        self.debug = debug
        if self.debug:
            print (self.name + " init")
        # Work-around for OXM-43: Intermittently Telit devices doesn't exist when system boot up
        attempt = 1
        while (attempt <= xcModemSer.MAX_ATTEMPT):
            try:
                self.freeser = serial.Serial(self.name, 115200, timeout=0, rtscts=0)
            except IOError as e:
                LOG.error("%s %s - Work-around attempt %s" % (self.name, e, attempt))
                cmd = ('xc_modem_gsm.sh -R 0; sleep 3; xc_modem_gsm.sh -R 1; xc_modem_gsm.sh -w "%s"' % dev)
                # LOG.debug("issuing: " + cmd)
                subprocess.call(cmd, shell=True)
                attempt += 1
            else:
                break;

    def send(self, string):
        if self.debug:
            print (self.name + " send:" + string)
        try:
            self.freeser.write(string)
        except AttributeError as e:
            LOG.error("%s %s" % (self.name, e))
            result = 0
        else:
            result = 1
        return result

    def sendavail(self):
        return 4096

    def read(self):
        try:
            string = self.freeser.read(512)
        except AttributeError as e:
            LOG.error("%s %s" % (self.name, e))
            string = ''
        return string

    def receive(self, timeout=2):
        res = ''
        start = time.time()
        while (time.time() - start < timeout):
            res = res + self.read()
            msleep(100)
        if self.debug:
            print (self.name + " recv:" + res)
        return res

    def sendbyte(self, byte):
        string = chr(byte)
        try:
            self.freeser.write(string)
        except AttributeError as e:
            LOG.error("%s %s" % (self.name, e))
            result = 0
        else:
            result = 1
        return result

    def readbyte(self):
        try:
            string = self.freeser.read(1)
            if string == '':
                result = -1
            else:
                result = ord(string)
        except AttributeError as e:
            LOG.error("%s %s" % (self.name, e))
        return result

    def setDCD(self, dcd):
        if dcd == 0:
            print 'dummy setDCD(0)'
        else:
            print 'dummy setDCD(1)'
        return

    def setCTS(self, cts):
        if cts == 0:
            print 'dummy setCTS(0)'
        else:
            print 'dummy setCTS(1)'
        return

    def setDSR(self, dsr):
        if dsr == 0:
            print 'dummy setDSR(0)'
        else:
            print 'dummy setDSR(1)'
        return

    def setRI(self, ri):
        if ri == 0:
            print 'dummy setRI(0)'
        else:
            print 'dummy setRI(1)'
        return

    def getRTS(self):
        print 'dummy getRTS()'
        rts = False
        if rts == False:
            result = 0
        else:
            result = 1
        return result

    def getDTR(self):
        print 'dummy getDTR()'
        dtr = False
        if dtr == False:
            result = 0
        else:
            result = 1
        return result

    def set_speed(self, speed, format='8N1'):
        result = 1
        try:
            if speed == '300':
                self.freeser.setBaudrate(300)
            elif speed == '600':
                self.freeser.setBaudrate(600)
            elif speed == '1200':
                self.freeser.setBaudrate(1200)
            elif speed == '2400':
                self.freeser.setBaudrate(2400)
            elif speed == '4800':
                self.freeser.setBaudrate(4800)
            elif speed == '9600':
                self.freeser.setBaudrate(9600)
            elif speed == '19200':
                self.freeser.setBaudrate(19200)
            elif speed == '38400':
                self.freeser.setBaudrate(38400)
            elif speed == '57600':
                self.freeser.setBaudrate(57600)
            elif speed == '115200':
                self.freeser.setBaudrate(115200)
            else:
                result = -1
            if result == 1:
                if format == '8N1':
                    self.freeser.bytesize = serial.EIGHTBITS
                    self.freeser.parity = serial.PARITY_NONE
                    self.freeser.stopbits = serial.STOPBITS_ONE
                elif format == '8N2':
                    self.freeser.bytesize = serial.EIGHTBITS
                    self.freeser.parity = serial.PARITY_NONE
                    self.freeser.stopbits = serial.STOPBITS_TWO
                elif format == '8E1':
                    self.freeser.bytesize = serial.EIGHTBITS
                    self.freeser.parity = serial.PARITY_EVEN
                    self.freeser.stopbits = serial.STOPBITS_ONE
                elif format == '8O1':
                    self.freeser.bytesize = serial.EIGHTBITS
                    self.freeser.parity = serial.PARITY_ODD
                    self.freeser.stopbits = serial.STOPBITS_ONE
                elif format == '7N1':
                    self.freeser.bytesize = serial.SEVENBITS
                    self.freeser.parity = serial.PARITY_NONE
                    self.freeser.stopbits = serial.STOPBITS_ONE
                elif format == '7N2':
                    self.freeser.bytesize = serial.SEVENBITS
                    self.freeser.parity = serial.PARITY_NONE
                    self.freeser.stopbits = serial.STOPBITS_TWO
                elif format == '7E1':
                    self.freeser.bytesize = serial.SEVENBITS
                    self.freeser.parity = serial.PARITY_EVEN
                    self.freeser.stopbits = serial.STOPBITS_ONE
                elif format == '7O1':
                    self.freeser.bytesize = serial.SEVENBITS
                    self.freeser.parity = serial.PARITY_ODD
                    self.freeser.stopbits = serial.STOPBITS_ONE
                elif format == '8E2':
                    self.freeser.bytesize = serial.EIGHTBITS
                    self.freeser.parity = serial.PARITY_EVEN
                    self.freeser.stopbits = serial.STOPBITS_TWO
                else:
                    self.freeser.bytesize = serial.EIGHTBITS
                    self.freeser.parity = serial.PARITY_NONE
                    self.freeser.stopbits = serial.STOPBITS_ONE
        except AttributeError as e:
            LOG.error("%s %s" % (self.name, e))
            result = -1
        return result

    def cmd_check(self, cmd, rsp, timeout=2):
        if self.send(cmd):
            r = self.receive(timeout)
            if re.search(rsp, r, re.M|re.I):
                return r
        return None


def ser_test():
    parser = argparse.ArgumentParser()
    parser.add_argument('dev', help='Serial Device')
    args = parser.parse_args()

    ser = xcModemSer(args.dev, debug = 1)
    while True:
        print "Input:",
        data = raw_input()
        if len(data) == 0: break
        ser.send(data + '\r')
        ser.receive(timeout=2)

if __name__ == '__main__':
    ser_test()
