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
import xc_json


class ParkingGarage:
 def __init__(self, name, pref, spaces, loc_lon, loc_lat, rate):
        self.name = name
        self.prefix = pref
        self.spaces_available = spaces
        self.max_spaces = spaces
        self.lon = loc_lon
        self.lat = loc_lat
        self.rate = rate
        self.count = 1


 def old_get_status(self):
       # jsonString = json.JSONEncoder().encode(
					  #[ { "name":"RSU", "value": self.name},	
					  #{ "name": self.prefix+" Spaces_available","value": self.spaces_available},
                                          #{ "name": self.prefix+" Longitude","value":self.lon},
                                          #{ "name": self.prefix+" Latitude","value":self.lat},
                                          #{ "name": self.prefix+" Cost/hour","value":self.rate},
					  #{ "name": self.prefix+" Count", "value":self.count}])

        jsonString = json.JSONEncoder().encode({
                                          "name": "RSU", "value": self.name,
                                          "extras": {
                                              "Spaces_available": self.spaces_available,
                                              "Longitude": self.lon,
                                              "Latitude": self.lat,
                                              "Cost/hour": self.rate,
                                              "Count": self.count,
                                              "extra, extra": "OpenXC-VI-V2X-6D00"}
                                          })

        self.spaces_available = random.randrange(0,self.max_spaces,1);
        self.rate = random.randrange(0,20,1);
        self.count += 1
        #data = json.dumps(jsonString)
        data = json.dumps(jsonString).strip("\"")  # To meet the message format guidelines can't have the double quotes around the packet
        tdata = (data.replace("}, {","}\\\0{")).replace("\\","")
#        LOG.info("TDATA = " + tdata)
        return(tdata.replace("\"[","")).replace("]\"","")+chr(0)   # Adding a \0 to the end of the packet per the message format standards

 def get_status(self):
	extras = {
		"Spaces_available": self.spaces_available,
		"Longitude": self. lon,
                "Latitude": self.lat,
                "Cost/hour": self.rate,
                "Count": self.count}
	propogation_options = [ xc_json.get_mac(), 0, 1, 1 ]
	
	tdata = xc_json.JSON_msg_encode("RSU", self.name, extras, propogation_options)
	self.spaces_available = random.randrange(0,self.max_spaces,1);
        self.rate = random.randrange(0,20,1);
        self.count += 1
	return tdata
