import json
import os
from time import time
from subprocess import check_output

def get_mac():
	my_mac = check_output("hcitool dev | awk \'/hci0/ {print $2}\'", shell=True)
        return my_mac.replace(':',"").strip()

def JSON_pass_logic(msg):
        required_parameters = ["time_to_live", "hops_to_live", "hops", "timestamp"]
        msg_dict = JSON_msg_decode(msg)
        if msg_dict is None:
                return -1

        proceed = True
        for param in required_parameters:
                if not (param in msg_dict["meta"] or (param is "timestamp" and param in msg_dict)):
                        proceed = False

        if proceed:
                TTL = int(msg_dict["meta"]["time_to_live"])
                HTL = int(msg_dict["meta"]["hops_to_live"])
                hops = int(msg_dict["meta"]["hops"])

                if "timestamp" in msg_dict["meta"]:
                        timestamp = float(msg_dict["meta"]["timestamp"])
                elif "timestamp" in msg_dict:
                        timestamp = float(msg_dict["timestamp"])
                elif TTL > 0:
                        print "ERROR: Time to live selected but no timestamp provided!"
                        print "Message: %s" % msg

                if (TTL == 0 and HTL == 0) or (TTL < 0 or HTL < 0):
                        return 3
                elif TTL > 0:
                        if timestamp + TTL > time():
                                if HTL == 0 or (HTL > 0 and hops + 1 <= HTL):
                                        return 3

                else:
                        if hops + 1 <= HTL:
                                return 3

        return 0

# Creates a json string suitable for sending over the 802.11p link on the V2X accessory
# Argument descriptions
# Returns string on success, None on failure
def JSON_msg_encode(name, value, extras, prop_ops):
	if not (prop_ops is None or len(prop_ops) == 4):
		print "Incorrect formatting of prop_ops argument."

		# TODO: There's a more efficient type to use to store the MAC, should use that instead eventually

		print "Usage: [(str) source MAC, (int) time to live, (int) hops to live, (int) current hops]"
		print "Propogation options may also be 'None' in which case metadata will be omitted"
		return None

	if not type(extras) is dict and not extras is None:
		print "Argument extras expects either a dictionary or NoneType"
		return None

	data_dict = {}
	data_dict["extras"] = extras
	data_dict["value"] = value
	data_dict["name"] = name
	if not prop_ops is None:
		meta = {"hops": prop_ops[3], "hops_to_live": prop_ops[2], "time_to_live": prop_ops[1], "forwarder": get_mac(), "source": prop_ops[0], "timestamp": time()}
		data_dict["meta"] = meta
	data_dict["timestamp"] = time()

	data_str = json.JSONEncoder().encode(data_dict)

	#return json.dumps(data_str)
	return data_str

def JSON_msg_decode(msg):
	if type(msg) is dict:
		msg_data = msg
	elif type(msg) is str:
                try:
		    msg_data = json.JSONDecoder().decode(msg.strip(chr(0)))
                except ValueError:
                    print "Error: multiple packets in this string.  Only returning the first one" # If this becomes an issue a more elegant solution can be found in the future
                    msg = msg.strip(chr(0)).replace("}{",'}'+chr(0)+'{').split(chr(0))[0]
                    msg_data = json.JSONDecoder().decode(msg.strip(chr(0)))
	else:
		print "ERROR: Unrecognized type (%s) of argument to JSON_msg_decode!" % type(msg)
		return None

	if "extras" in msg_data and type(msg_data["extras"]) is str:
		msg_data["extras"] = json.loads(msg_data["extras"])
	if "meta" in msg_data and type(msg_data["meta"]) is str:
		msg_data["meta"] = json.loads(msg_data["meta"])

	return msg_data

if __name__ == '__main__':

	# Encoding tests

	extras = {
                "Spaces_available": 12,
                "Longitude": 17,
                "Latitude": 5,
                "Cost/hour": 2,
                "Count": 1}
        propogation_options = [ get_mac(), -1, 1, 0 ]

        json_str = JSON_msg_encode("RSU", "RSU_Name", extras, propogation_options)
	print "json_str (%s): %s" % (type(json_str), json_str)

	# Decoding tests

	json_dict = JSON_msg_decode(json_str)
	print "json_dict (%s): %s" % (type(json_dict), json_dict)
