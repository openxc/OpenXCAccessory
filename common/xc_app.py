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

import os

from xc_common import *
from xc_cmd import *
from xc_vi import vi_cleanup
import errno
from socket import error as socket_error


APP_RECONNECT = True

try:
    import bluetooth
except ImportError:
    LOG.debug("pybluez library not installed, can't use bluetooth interface")
    bluetooth = None


def sdp_prep(port):
    # SDP queries on bluetooth devices
    cmd = 'sdptool browse local | grep "Channel: %s"' % port
    # LOG.debug("issuing: " + cmd)
    if subprocess.call(cmd, shell=True, stdout=subprocess.PIPE):
        cmd = 'sdptool add --channel=%s SP' % port
        # LOG.debug("issuing: " + cmd)
        subprocess.call(cmd, shell=True, stdout=subprocess.PIPE)

#---------------------------------------------
# check for message exchange with mobile phone
# to determine if  phone is ready
#---------------------------------------------
def set_mb_ready():
    if ((mb_status['modem_id_sent']) and (mb_status['modem_version_sent']) and (mb_status['v2x_id_sent']) and (mb_status['v2x_version_sent'])):
       time.sleep(1)
       mb_status['ready'] = True
       mb_status['vi_id_sent'] = False
       mb_status['vi_version_sent']  = False
       mb_status['modem_id_sent']  = False
       mb_status['modem_version_sent']  = False
       mb_status['v2x_id_sent']  = False
       mb_status['v2x_version_sent'] = False

#---------------------------------------------------------
#  Open the socket with  mobile app
#---------------------------------------------------------

def app_listening(name, port ):
    # Establish server/slave port listenning
    serverSock=bluetooth.BluetoothSocket(bluetooth.RFCOMM)
    serverSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serverSock.bind(("", port))
    # LOG.info("Listen on BT port %s" % port)
    # OXM-72: use timeout to break listening socket so we can restart bluetooth
    serverSock.settimeout(1)
    serverSock.listen(1)
    while True:
        try:
            clientSock,address = serverSock.accept()
        except BluetoothError as e:
            # socket.timeout is presented as BluetoothError w/o errno
            if e.args[0] == 'timed out':
                if not exit_flag['bt_restart']:
                    continue
                LOG.debug("timeout stop " + name)
            else:
                LOG.debug("%s %s" % (name, e))
            exit_flag[name] = 1
            serverSock.shutdown(socket.SHUT_RDWR)
            serverSock.close()
            LOG.info("No listner, Timed out, closing BT")
            return (None, None, None)
        else:
            LOG.info("Got a connection")
            break
    LOG.info("Accepted connection from %s", address)
    return (serverSock, clientSock, address)

#---------------------------------------------------------
#  Class for communication with Mobile App
#---------------------------------------------------------
class appThread (threading.Thread):
    def __init__(self, name, port, inQ, outQ, passthruQ, passQ):
        threading.Thread.__init__(self)
        self.name = name
        self.port = port
        self.inQ = inQ
        self.outQ = outQ
        self.passthruQ = passthruQ
        self.passQ = passQ
        self.running = True
        #self.v2x = boardid_inquiry() == 2
        self.v2x = boardid_inquiry()
        self.threads = []
        self.firstpass = 1


    def run(self):
        while not exit_flag['all_app']:

            # OXM-72: not start until bt_restart done
            while exit_flag['bt_restart']:
                time.sleep(1)
            LOG.debug("Starting " + self.name)

            LOG.info("Re opening BT port")

            modem_state[self.name] = app_state.PENDING
            exit_flag[self.name] = 0
            vi_bypass[self.name] = False
            #vi_bypass[self.name] = True

            while not exit_flag['all_app']:
                # OXM-72: need to prep sdp again since BT might have just been restarted
                sdp_prep(self.port)
                serverSock, clientSock, address = app_listening(self.name, self.port)

                # OXM-72: listening socket might be timeout with exit_flag
                if exit_flag[self.name]:
                    break

                # Paired VI might incidently connect to the reserved port
                # Thus, we need to check for authorize device
                addr = address[0]
                cmd = "bluez-test-device list | awk '/%s/ {print $2}'" % addr
                # LOG.debug("issuing " + cmd)
                cmd_op = subprocess.check_output(cmd, shell=True).split()
                if (len(cmd_op) > 0):
                   device = subprocess.check_output(cmd, shell=True).split()[0]
                else:
                   device = "NOT Found"
                if (self.name == 'mb_app' and \
                    not device.startswith(OPENXC_DEVICE_NAME_PREFIX)) or \
                   (self.name == 'md_app' and \
                    device.startswith(OPENXC_V2X_NAME_PREFIX)):
                    break
                LOG.debug("%s unpair un-authorized connection %s %s" % (self.name, device, address))
                cmd = "bluez-test-device remove " + addr
                if subprocess.call(cmd, shell=True):
                    LOG.debug(self.name + " fail to unpair unauthorized device")
                clientSock.shutdown(socket.SHUT_RDWR)
                clientSock.close()
                serverSock.shutdown(socket.SHUT_RDWR)
                serverSock.close()

            # OXM-72: listening socket might be timeout with exit_flag
            if exit_flag[self.name]:
                LOG.debug("Ending " + self.name)
                continue

            modem_state[self.name] = app_state.CONNECTED
            port_mac[self.name] = addr

            # create new threads
            thread1 = sockRecvThread("%s-Recv" % self.name, clientSock, self.inQ, self.name)
            thread2 = sockDualSendThread("%s-Send" % self.name, clientSock, self.outQ, self.passthruQ, self.name)
            # start threads
            thread1.start()
            thread2.start()

            self.threads.append(thread1)
            self.threads.append(thread2)

            modem_state[self.name] = app_state.OPERATION

            while not exit_flag[self.name]:
                if not self.inQ.empty():
                    # Commenting all of this out because in the caravan demo the version numbers and IDs of the connected devices are not needed
                    # In the future this entire section should be overhauled because it does not support sending data from the phone to the V2X other than the commands hard-coded into the functions called here
                    #cmd = self.inQ.get()
                    #print "appThread cmd = {0}".format(cmd)
                    #if self.name == 'mb_app':
                    #    mb_process_data(self.v2x, self.name, self.passthruQ, self.passQ, cmd)
                    #elif self.name == 'md_app':
                    #    md_process_data(self.v2x, self.name, self.outQ, self.passQ, cmd)
                    #set_mb_ready()
                    pass
                msleep(1)

             # waif for threads finish
            for t in self.threads:
               t.join()

            clientSock.shutdown(socket.SHUT_RDWR)
            clientSock.close()
            serverSock.shutdown(socket.SHUT_RDWR)
            serverSock.close()
            # flush the queues
            while not self.inQ.empty():
                self.inQ.get()
            while not self.outQ.empty():
                self.outQ.get()
            LOG.debug("Ending " + self.name)
            modem_state[self.name] = app_state.DONE
            if not APP_RECONNECT:
                break;
            time.sleep(1)

#-----------------------------------------------------------
# Application for opening socket with V2X
#-----------------------------------------------------------
def appSock_listening(name, port ):
    # Establish server/slave port listenning
    LOG.info("Entering appSock_listening")
    ip_addr = conf_options['xcmodem_ip_addr']
    if (name  == 'm_2_v2x'):
    	serverSock=socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    	LOG.debug("Listen on INET port %s" % port)
        serverSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    	serverSock.bind((ip_addr, port))

    else:
        LOG.debug("Invalid SocketApp type");

    # OXM-72: use timeout to break listening socket so we can restart bluetooth
    serverSock.settimeout(1)
    serverSock.listen(1)
    while True:
        try:
            clientSock,address = serverSock.accept()
        except socket_error as e:
            # socket.timeout is presented as BluetoothError w/o errno
            if e.args[0] == 'timed out':
                if not exit_flag['all_app']:
                    continue
                LOG.debug("timeout stop " + name)
            else:
                LOG.debug("%s %s" % (name, e))
            LOG.info("Shtting down socket as there are no listeners")
            exit_flag[name] = 1
            serverSock.shutdown(socket.SHUT_RDWR)
            serverSock.close()
            return (None, None, None)
        else:
            break
    LOG.info("Accepted connection from %s", address)
    return (serverSock, clientSock, address)
#---------------------------------------------------------------------------


#-----------------------------------------------------------
# class to handle communication with  V2X
#-----------------------------------------------------------
class appSockThread (threading.Thread):
    def __init__(self, name, port, inQ, outQ, passQ):
        threading.Thread.__init__(self)
        self.name = name
        self.port = port
        self.inQ = inQ
        self.outQ = outQ
        self.passQ = passQ
        self.running = True
        self.v2x = boardid_inquiry() == 2


    def run(self):
        while not exit_flag['all_app']:
            # OXM-72: not start until bt_restart done
            while exit_flag['bt_restart']:
                time.sleep(1)
            LOG.debug("Starting " + self.name)

            modem_state[self.name] = app_state.PENDING
            exit_flag[self.name] = 0
            vi_bypass[self.name] = False

            while not exit_flag['all_app']:
                # OXM-72: need to prep sdp again since BT might have just been restarted
                LOG.info("Trying to open a socket on port %s" % self.port)
                serverSock, clientSock, address = appSock_listening(self.name, self.port)
                if (clientSock  is not None):
                  LOG.info("Got a non null Client address")
                  break

                # OXM-72: listening socket might be timeout with exit_flag
                if exit_flag[self.name]:
                    LOG.info("Found self exit flag")
                    break


            # OXM-72: listening socket might be timeout with exit_flag
            if exit_flag[self.name]:
                LOG.debug("Ending " + self.name)
                continue

            LOG.info("===========================================")
            LOG.info("=====> Modem Socket port open and connected")
            LOG.info("===========================================")
            modem_state[self.name] = app_state.CONNECTED
            port_mac[self.name] = address[0]

            # create new threads
            thread1 = sockRecvThread("%s-Recv" % self.name, clientSock, self.inQ, self.name)
            thread2 = sockSendThread("%s-Send" % self.name, clientSock, self.outQ, self.name)
            # start threads
            thread1.start()
            thread2.start()
            modem_state[self.name] = app_state.OPERATION

            # waif for threads finish
            thread1.join()
            thread2.join()

            try:
                ClientSock.shutdown(socket.SHUT_RDWR)
            except:
                LOG.info("connection does not exist")
            else:
               LOG.info("Shutdown the listner socket")

            clientSock.close()
            serverSock.shutdown(socket.SHUT_RDWR)
            serverSock.close()
            # flush the queues
            while not self.inQ.empty():
                self.inQ.get()
            while not self.outQ.empty():
                self.outQ.get()
            LOG.debug("Ending " + self.name)
            modem_state[self.name] = app_state.DONE
            if not APP_RECONNECT:
                break;
            time.sleep(1)
#-----------------------------------------------------------

if __name__ == '__main__':
    threads = []
    pairing_registration()
    vi_cleanup()

    boardid_inquiry(1)
    if port_dict['pc_app']['enable']:
        thread = appThread('pc_app', port_dict['pc_app']['port'], pc_in_queue, pc_out_queue, vi_out_queue)
        thread.start()
        threads.append(thread)

    if port_dict['mb_app']['enable']:
        thread = appThread('mb_app', port_dict['mb_app']['port'], mb_in_queue, mb_out_queue, vi_out_queue)
        thread.start()
        threads.append(thread)

    if port_dict['md_app']['enable']:
         thread = appThread('md_app', port_dict['md_app']['port'], md_in_queue, md_out_queue, md_passthru_queue, vi_out_queue)
         thread.start()
         threads.append(thread)


    # Wait for all threads to complete
    for t in threads:
        t.join()

    LOG.info("Exiting Main Thread")
