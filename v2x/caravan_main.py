#!/usr/bin/python
import caravan_helpers as caravan
import logging
import sys

sys.path.append("../common")
from xc_common import *
from xc_vi import *
from xc_app import *
from xc_rsu_common import *

logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('caravan')

try:
    import bluetooth
except ImportError:
    LOG.debug("Can't use Bluetooth, pybluez library not installed!")
    bluetooth = None

def main(sdebug = 0, debug = 0):
    threads = []
    rdata = ""
    sdata = ""
    attempt = 0

    # Set values for timers
    CARAVAN_ADVERT_DELAY = 3            # Time (in seconds) between advertisements about the availability of a caravan hosted by this device
    last_caravan_advert = float(0)      # Time of last caravan advertisement sent by this device
    VEHICLE_PRES_DELAY = 5              # Delay (in seconds) between vehicle presence messages broadcast by this device
    last_veh_pres = float(0)            # Time of last vehicle presence message from this device

    LOG.info("OpenXC Caravan Demonstration")
    myhost = os.uname()[1]
    LOG.info(myhost)

    # Clear out the queue in case it has stale data
    while not mb_out_queue.empty():
        mb_out_queue.get()

    # Start the VI  TODO Can we add verbosity level to these functions so the terminal isn't filled with (mostly) useless data at the launch of the application
    pairing_registration()
    vi_cleanup()
    vi_dev = xcModemVi(port_dict['vi_app']['port'], vi_in_queue, vi_out_queue, sdebug, debug)
    vi_dev.file_discovery('xc.conf')

    # Check that the VI came up successfully
    if conf_options['openxc_vi_enable'] == 1:
        vi_status = vi_dev.vi_main()
        while ( not vi_status)and (attempt < MAX_BRING_UP_ATTEMPT):
            time.sleep(float(conf_options['openxc_vi_discovery_interval']))
            attempt += 1
            vi_status = vi_dev.vi_main()
        if conf_options['openxc_vi_enable'] == 1:
            if (not vi_status):
                LOG.error("Failed to bring up the VI!")
                sys.exit()
        else:
            vi_status = 0

    # Start the RSU
    xcV2Xrsu_dev = xcV2Xrsu('v2x_2_rsu',port_dict['xcV2Xrsu_tx']['port'],port_dict['xcV2Xrsu_rx']['port'], xcV2Xrsu_in_queue, xcV2Xrsu_out_queue, sdebug, debug)

    # Check the RSU came up successfully
    xcV2Xrsu_status = xcV2Xrsu_dev.xcV2Xrsu_main();
    while ( not xcV2Xrsu_status)and (attempt < MAX_BRING_UP_ATTEMPT):
        time.sleep(float(conf_options['openxc_vi_discovery_interval']))
        attempt += 1
        xcV2Xrsu_status = xcV2Xrsu_dev.xcV2Xrsu_main()

    if (not xcV2Xrsu_status):
        LOG.error("Failed to bring up the RSU!")
        sys.exit()

    # Starting the Mobile App Thread
    if port_dict['mb_app']['enable']:
        LOG.info("Starting Mobile App...")
        thread = appThread('mb_app', port_dict['mb_app']['port'], mb_in_queue, mb_out_queue, mb_passthru_queue, passQ)
        thread.start()
        threads.append(thread)

    while not exit_flag['vi_app']:

        # Check for Mobile Data
        if (not mb_in_queue.empty()):
            rdata = rdata + mb_in_queue.get().replace("{}","")
        if (len(rdata) > 10):
            mobile_data = cleanup_json(rdata)   # <- TODO Is this still needed?
            rdata = ""
            if len(mobile_data) > 0:
                print "----------\nReceived (Mobile): {0}".format(mobile_data)

                # Handle mobile data
                caravan.mobile_parse(mobile_data, [xcV2Xrsu_in_queue, xcV2Xrsu_out_queue], [mb_in_queue, mb_out_queue])

        # Check for DSRC Data
        if (not xcV2Xrsu_in_queue.empty()):
            sdata = sdata + xcV2Xrsu_in_queue.get().replace("{}","")
        if (len(sdata) > 200):
            DSRC_data = cleanup_json(sdata) # <- TODO Is this still needed?
            sdata = ""
            if len(DSRC_data) > 0:
                print "----------\nReceived (DSRC): {0}".format(DSRC_data)

                # Handle the DSRC data
                caravan.DSRC_parse(DSRC_data, [xcV2Xrsu_in_queue, xcV2Xrsu_out_queue], [mb_in_queue, mb_out_queue])

        # Check for VI data
        if (conf_options['openxc_vi_enable']):
            if not vi_in_queue.empty():
                tdata = tdata + vi_in_queue.get()
                if (len(tdata) > 200):
                    data = cleanup_json(tdata)
                    tdata = ""
                    if not data is None:
                        pass # Parse the VI data and pass it along to Mobile or DSRC

        # Timers for when to declare a "nearby" vehicle out of range and when to send vehicle presence messages ourselves

        # State machine
        last_state = caravan.status["STATE"]
        # Where all devices begin, waiting for information from the mobile to determine what mode the device is in and what to do going forward
        if caravan.status["STATE"] == caravan.IDLE:
            if caravan.status["MODE"] == caravan.HOST and caravan.host_caravan["status"] == caravan.SETUP:
                caravan.status["STATE"] = caravan.NEW
            elif caravan.status["MODE"] == caravan.MEMBER:
                caravan.status["STATE"] = caravan.SEARCH

        # Host vehicle advertising the presence of its caravan waiting for it to fill up/timeout/be closed by the user
        elif caravan.status["STATE"] == caravan.NEW:
            if time.time() - last_caravan_advert >= CARAVAN_ADVERT_DELAY:
                caravan.caravan_advert(xcV2Xrsu_out_queue)
                last_caravan_advert = time.time()

            if caravan.host_caravan["status"] == caravan.RUNNING:    # <-- TODO: There should be a timeout as well and a method for the phone to close the caravan early
                caravan.status["STATE"] = caravan.ACTIVE
                # Send message to the paired phone indicating opening of caravan?
                # Broadcast DSRC message of opened caravan?

        # Member collecting advertisements from nearby caravans but hasn't requested to join one yet
        elif caravan.status["STATE"] == caravan.SEARCH:
            pass

        # A member which has submitted a request to join a caravan and is waiting to hear back
        elif caravan.status["STATE"] == caravan.REQUEST:
            pass

        # Normal state of operation once the vehicle has been accepted into a caravan - most time should be spent here
        elif caravan.status["STATE"] == caravan.ACTIVE:
            if time.time() - last_veh_pres >= VEHICLE_PRES_DELAY:   # Check timers and send vehicle presence at the desired interval TODO: Should this be outside the state machine
                caravan.vehicle_presence(xcV2Xrsu_out_queue)
                last_veh_pres = time.time()

            if not last_state == caravan.ACTIVE:
                # Tell the members the caravan is officially open!
                pass

        # If the vehicle gets separated from the rest of the group (i.e doesn't hear anther member's ping for a certain time)
        elif caravan.status["STATE"] == caravan.LOST:
            pass

        # Cleaning everything up, returns to IDLE in case a new caravan session is desired
        elif caravan.status["STATE"] == caravan.END:
            # Reset everything to defaults (except vehicle status?)
            caravan.my_vehicle = {"id": xc_json.get_mac(), "pretty": None, "year": "0000", "make": "MAKE", "model": "MODEL"} # Reset vehicle info
            caravan.vehicles = []   # Clear out the list of nearby vehicles
            caravan.my_caravan = {"id": None, "pretty": None, "members": []}    # Information about the caravan this V2X is a part of
            caravan.host_caravan = {"in_use": False, "id": None, "pretty": None, "protected": False, "pw": None, "count": 1, "max": 5, "members": []}    # Even for the host the data is wiped
            caravan.caravans = {}   # Clear out stale caravans
            caravan.status = {"MODE": None, "STATE": caravan.IDLE} # No longer know what mode we are, go back to IDLE and wait

        else:
            print "Error!  Unknown state {0}.  Going to END".format(caravan.status["STATE"])
            caravan.status["STATE"] = caravan.END

        if not caravan.status["STATE"] == last_state:
            print "Transition {0} -> {1} occured".format(last_state, caravan.status["STATE"])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', help='Verbosity Level (-2..2)')
    args = parser.parse_args()
    restart = 1;

    if args.v is None:
        level = 0
    else:
        level = int(args.v)

    if level < -1:
        LOG.setLevel(level=logging.WARN)
    elif level < 0:
        LOG.setLevel(level=logging.INFO)
    main(sdebug = (level>1), debug = (level>0))
