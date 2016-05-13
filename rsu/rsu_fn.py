#!/usr/bin/python

# $Rev:: 237           $
# $Author:: mlgantra   $
# $Date:: 2015-03-31 1#$
#
# openXC-modem application agents thread and associated functions

import Queue
import threading
import time
import subprocess

from xc_common import *
from xc_cmd import *
#from xc_vi import vi_cleanup
import errno
from socket import error as socket_error
import random
import json 


class ParkingGarage:
 def __init__(self, name, spaces, loc_lon, loc_lat, rate):
        self.name = name
        self.spaces_available = spaces
        self.max_spaces = spaces
        self.lon = loc_lon
        self.lat = loc_lat
        self.rate = rate


 def get_status(self):
        jsonString = json.JSONEncoder().encode(
                                          [ {},
					  { "name":self.name+"spaces_available","value": self.spaces_available},
                                          { "name":self.name+"lon","value":self.lon},
                                          { "name":self.name+"lat","value":self.lat},
                                          { "name":self.name+"rate","value":self.rate}])

        self.spaces_available = random.randrange(0,self.max_spaces,1);
        data = json.dumps(jsonString)
        tdata = (data.replace("}, {","}\\\0{")).replace("\\","")
#        LOG.info("TDATA = " + tdata)
        return(tdata.replace("\"[","")).replace("]\"","")


