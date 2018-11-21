#!/usr/bin/python

import sys

sys.path.append("../common")
import xc_json

# My constants
IDLE, NEW, SEARCH, REQUEST, ACTIVE, LOST, END = range(7)
FREE, SETUP, RUNNING = range(3)
HOST, MEMBER = range(2)

# Set up the variables to keep track of caravan and vehicle data
my_vehicle = {"id": xc_json.get_mac(), "pretty": None, "year": "0000", "make": "MAKE", "model": "MODEL"} # Information about the vehicle this V2X unit represents
vehicles = [] # General inforamtion about nearby vehicles
my_caravan = {"id": None, "pretty": None, "members": {}} # Information about the caravan this V2X is a part of
host_caravan = {"status": FREE, "id": None, "pretty": None, "protected": False, "pw": None, "count": 1, "max": 5, "members": None} # Backend information about the caravan (only used by hosts)
caravans = {} # Information about nearby caravans which are advertising
status = {"MODE": None, "STATE": SEARCH} # Method of tracking whether this V2X belongs to a host or a member (MODE) and what stage it is operating in (STATE)# Converts the "pretty" name for a caravan to the MAC of the V2X unit associated with it

def caravan_pretty2mac(pretty):
    global caravans
    for key in caravans:
        if caravans[key]["pretty"] == pretty:
            return key
    return -1

# Takes a message received over DSRC, breaks it apart, and performs the appropriate action
def DSRC_parse(msg, DSRC_Qs, mobile_Qs):
    msg_dict = xc_json.JSON_msg_decode(msg)

    [DSRC_inQ, DSRC_outQ] = DSRC_Qs
    [mobile_inQ, mobile_outQ] = mobile_Qs

    my_mac = xc_json.get_mac()
    extras = msg_dict["extras"]
    meta = msg_dict["meta"]
    if msg_dict["name"] == "caravan_data":
        # A caravan is available to be joined - these are broadcasted by hosts at set intervals - Can be ignored when we're not in "roaming" mode?
        if msg_dict["value"] == "available_caravan":
            print "Got available caravan notification from {0} ({1})!".format(extras["pretty"],extras["id"])
            if extras["id"] in caravans:
                # Check and update if anything doesn't match
                for key in extras:
                    try:
                        if not caravans[extras["id"]][key] == extras[key]:
                            caravans[extras["id"]][key] = extras[key]
                    except: # TODO: Make this a finally instead and simplify the code in the try portion?
                        caravans[extras["id"]][key] = extras[key]
            else:
                # Update the caravan list with this data
                temp_dict = {}
                for key in extras:
                    if not key == "id":
                        temp_dict[key] = extras[key]
                caravans[extras["id"]] = temp_dict

        # Message sent by each vehicle at regular intervals announcing status and providing a mechanism for other vehicles to know they are in range
        elif msg_dict["value"] == "veh_pres":
            # Check that the vehicle is on the list of vehicles for my caravan
            pass

        # A request to join an open caravan hosted by this device
        elif msg_dict["value"] == "join_req":
            # Check 1. This device is the intended recipient, and 2. that this device is a host
            if extras["to"] == my_mac and status["MODE"] == HOST:
                if status["STATE"] == NEW:
                    # Check that caravan is not "full"
                    if host_caravan["count"] < host_caravan["max"]:
                        # Is password (if required) correct?
                        if (host_caravan["protected"] and extras["pw"] == host_caravan["pw"]) or not host_caravan["protected"]:  # <-- TODO This is an absolutely horrible, insecure way to do this.  Fix this some day
                            host_caravan["count"] += 1
                            if host_caravan["members"] is None:
                                member_list = {}
                                member_list[my_vehicle["id"]] = {"pretty": my_vehicle["pretty"], "year": my_vehicle["year"], "make": my_vehicle["make"], "model": my_vehicle["model"], "num_pass": my_vehicle["num_pass"]}
                                DSRC_outQ.put(xc_json.JSON_msg_encode("caravan_data","join_resp",{"to": meta["source"], "result": "GRANTED", "members": member_list}, [my_mac, 0, 1, 0]))
                                host_caravan["members"] = {}
                            else:
                                member_list = host_caravan["members"]
                                member_list[my_vehicle["id"]] = {"pretty": my_vehicle["pretty"], "year": my_vehicle["year"], "make": my_vehicle["make"], "model": my_vehicle["model"], "num_pass": my_vehicle["num_pass"]}
                                DSRC_outQ.put(xc_json.JSON_msg_encode("caravan_data","join_resp",{"to": meta["source"], "result": "GRANTED", "members": member_list}, [my_mac, 0, 1, 0]))

                            mobile_outQ.put(xc_json.JSON_msg_encode("caravan_data","new_member",{"pretty": extras["pretty"], "year": extras["year"], "make": extras["make"], "model": extras["model"], "num_pass": extras["num_pass"]}, None))    # Let the phone know
                            host_caravan["members"][meta["source"]] = {"pretty": extras["pretty"], "year": extras["year"], "make": extras["make"], "model": extras["model"], "num_pass": extras["num_pass"]}
                        else:
                            DSRC_outQ.put(xc_json.JSON_msg_encode("caravan_data","join_resp",{"to": meta["source"], "result": "DENIED", "reason": "Incorrect password."}, [my_mac, 0, 1, 0]))
                    else:
                        DSRC_outQ.put(xc_json.JSON_msg_encode("caravan_data","join_resp",{"to": meta["source"], "result": "DENIED", "reason": "This caravan is full."}, [my_mac, 0, 1, 0]))
                else:
                    DSRC_outQ.put(xc_json.JSON_msg_encode("caravan_data","join_resp",{"to": meta["source"], "result": "DENIED", "reason": "This caravan is no longer accepting new members."}, [my_mac, 0, 1, 0]))

        # A response from a caravan host indicating approval or rejection to join
        elif msg_dict["value"] == "join_resp":
            if extras["to"] == my_mac and status["STATE"] == REQUEST:
                if extras["result"] == "GRANTED":
                    # Update the caravan data
                    for key in my_caravan:
                        try:
                            my_caravan[key] = extras[key]
                        except:
                            print "Key {0} not in extras for message {1}, that's not good :(".format(key, msg)
                    # Tell phone connection is good
                    mobile_outQ.put(xc_json.JSON_msg_encode("caravan_data","join_resp",{"result": "GRANTED"}, None))
                    status["STATE"] = ACTIVE
                else:
                    # Pass the phone a denied connection message along with the reason
                    mobile_outQ.put(xc_json.JSON_msg_encode("caravan_data","join_resp",{"result": "DENIED", "reason": extras["reason"]}, None))
                    status["STATE"] = SEARCH

        # Text message sent from one vehicle to the entire group (or possibly another vehicle specifically some day)
        elif msg_dict["value"] == "text_msg":
            if status["STATE"] == ACTIVE:
                if (status["MODE"] and meta["source"] in my_caravan["members"]) or (not status["MODE"] and meta["source"] in host_caravan["members"]): # Need to check if the message is meant for my caravan
                    print "Got text from {0} ({1}), passing to phone.".format(extras["from"], meta["source"])
                    mobile_outQ.put(xc_json.JSON_msg_encode("caravan_data","text_rcv",{"from": extras["from"], "body": extras["body"], "sent": extras["sent"]}, None))
                else:
                    print "Got text from non-caravan member {0} ({1}), ignoring.".format(extras["from"],meta["source"])

        # A poll is available (sent from a host vehicle to the other members)
        elif msg_dict["value"] == "new_poll":
            pass

        # A member vehicle's response to a poll
        elif msg_dict["value"] == "poll_resp":
            pass

        # The resulsts of a previous poll disctributed to the members whether or not they voted
        elif msg_dict["value"] == "poll_result":
            pass

        else:
            LOG.debug("Unrecognized message value ({0}), ignoring".format(msg_dict["value"]))
    elif msg_dict["name"] == "rsu_data":
        pass

    else:
        LOG.debug("Unrecognized message name ({0}), ignoring".format(msg_dict["name"]))

# Takes a message from the mobile app, breaks it into components and performs the required actions
def mobile_parse(msg, DSRC_Qs, mobile_Qs):
    msg_dict = xc_json.JSON_msg_decode(msg)

    [DSRC_inQ, DSRC_outQ] = DSRC_Qs
    [mobile_inQ, mobile_outQ] = mobile_Qs

    my_mac = xc_json.get_mac()

    if "extras" in msg_dict:
        extras = msg_dict["extras"]
    else:
        extras = None

    if not "value" in msg_dict or not "name" in msg_dict:
        return  # The message is a command, pitch it

    if msg_dict["value"] == "role":
        if extras["role"] == "HOST":
            status["MODE"] = HOST
            #if not my_vehicle["pretty"] is None:
            #    host_caravan["members"][my_mac] = my_vehicle
        else:
            status["MODE"] = MEMBER
        print "Updated role, this device is a {0}.".format(status["MODE"])

    elif msg_dict["value"] == "veh_setup":
        for key in extras:
            if not key == "role":
                my_vehicle[key] = extras[key]
        print "Updated vehicle attributes - my_vehicle = {0}".format(my_vehicle)

    elif msg_dict["value"] == "list_caravans":
        if not status["MODE"] == HOST and status["STATE"] == SEARCH:
            temp_dict = {}
            for caravan_id in caravans:
                temp_dict[caravan_id] = caravans[caravan_id]
            mobile_outQ.put(xc_json.JSON_msg_encode("caravan_data","caravans", temp_dict, None))
            print "Caravan list sent to mobile - caravans = {0}".format(caravans)

    elif msg_dict["value"] == "join_caravan":
        if not status["MODE"] == HOST and status["STATE"] == SEARCH:
            temp_dict = {"pw": extras["pw"], "to": caravan_pretty2mac(extras["pretty"])}
            for key in my_vehicle:
                if not key == "id":
                    temp_dict[key] = my_vehicle[key]
            DSRC_outQ.put(xc_json.JSON_msg_encode("caravan_data", "join_req", temp_dict, [my_mac, 0, 1, 0]))
            print "Sent join request to {0} ({1})".format(extras["pretty"], temp_dict["to"])
            status["STATE"] = REQUEST

    elif msg_dict["value"] == "quit_caravan":
        # Not exactly sure what to do here or if it is even needed yet
        pass

    elif msg_dict["value"] == "kick":
        # Make sure you're the host
        # Add the mac of the member to be kicked to some sort of kick-queue
        pass

    elif msg_dict["value"] == "setup_caravan":
        if status["MODE"] == HOST and status["STATE"] == IDLE:
            host_caravan["status"] = SETUP
            # Assign all the caravan values to the ones in the message
            for key in extras:
                host_caravan[key] = extras[key]
            host_caravan["id"] = my_mac
            print "Caravan updated - host_caravan = {0}".format(host_caravan)

    elif msg_dict["value"] == "start_caravan":
        if status["MODE"] == HOST and status["STATE"] == SETUP:
            host_caravan["status"] = RUNNING

    elif msg_dict["value"] == "text_send":
        if status["STATE"] == ACTIVE:
            DSRC_outQ.put(xc_json.JSON_msg_encode("caravan_data", "text_msg", {"from": my_vehicle["pretty"], "body": extras["body"], "sent": extras["sent"]}, [my_mac, 0, 1, 0]))
        else:
            mobile_outQ.put(xc_json.JSON_msg_encode("caravan_data", "text_fail", {"reason": "Caravan has not \"started\" yet!"}, None))

# Information about the vehicle from CAN via the vehicle interface - only a subset of this data will be used
def vi_parse(msg):
    pass

def caravan_advert(outQ):
    extras = {}
    for key in host_caravan:
        if not key in ["status", "pw", "members"]:
            extras[key] = host_caravan[key]
    outQ.put(xc_json.JSON_msg_encode("caravan_data", "available_caravan", extras, [xc_json.get_mac(), 0, 1, 0]))
    #print "Sent caravan advertisement"

def vehicle_presence(outQ):
    pass

if __name__ == '__main__':
    # Test, Test, Test
    pass
