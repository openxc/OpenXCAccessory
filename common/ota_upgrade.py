#!/usr/bin/python

# $Rev:: 426           $
# $Author:: mlgantra   $
# $Date:: 2015-06-23 1#$
#
# openXC-Modem Vehicle Interface (VI) agent class and associated functions

import logging
import os.path
import subprocess
import re
import string
import sys
import time
import datetime
import os

sys.path.append('../common')
from xc_common import *
import xc_led
import xc_ver


logging.basicConfig(level=logging.DEBUG)
LOG = logging.getLogger('xcmodem')



def check_ping():

    if ((boardid_inquiry != 2) and (boardmode_inquiry != 3)):
      hostname = "www.yahoo.com"
      ping_cmd = "ping -c 3 -I wlan0 {0} > /dev/null 2>&1".format(hostname)
      ping_response = os.system(ping_cmd)
      return ping_response
    else:
      hostname = "20.0.0.1"
      ping_cmd = "ping -c 3 -I wlan0 {0} > /dev/null 2>&1".format(hostname)
      ping_response = os.system(ping_cmd)
      return ping_response

def v2x_lan_upgrade():
        ver_url = conf_options['v2x_lan_scp_sw_latest_version_url']
        if ver_url is None or ver_url == 'None':
            return
        LOG.debug("OTA auto upgrade validation.. ")
        # Use WiFi if applicable
        if not check_ping() == 0:
            # Use GSM if applicable 
            if conf_options['gsm_enable']:
            	if not self.gsm_instance():
                    LOG.error("OTA abort due to gsm_app instance fail")
                    return
            	if not self.gsm.start():
                    LOG.error("OTA abort due to gsm_app start fail")
                    # No need to move on without network connection
                    return 
        # Obtain latest version info
        cmd = "rm -fr /tmp/upgrade.ver; \
               sshpass -p root scp -o StrictHostKeyChecking=no %s@%s /tmp/upgrade.ver" % \
                (conf_options['v2x_lan_scp_userid'], \
                ver_url)
        # LOG.debug("issuing '%s'" % cmd)
        if subprocess.call(cmd, shell=True):
            LOG.error("fail to scp upgrade.ver from %s@%s" % (conf_options['v2x_lan_scp_userid'], \
                                                         ver_url))
            LOG.error("OTA abort due to scp fail")
            return
        ver, fname = subprocess.check_output("cat /tmp/upgrade.ver", shell=True).split()
        cver = xc_ver.get_version()
        LOG.debug("OTA latest=%s current=%s" % (ver, cver))
        if ver <= cver:
            return
        LOG.info("OTA auto upgrade for %s ..." % ver)
        # Obtain upgrading package
        if re.search(r'/', conf_options['v2x_lan_scp_sw_latest_version_url'], re.M|re.I):
            delimiter = '/'
        else:
            delimiter = ':'
        pkg = "%s%s%s" % (conf_options['v2x_lan_scp_sw_latest_version_url'].rsplit(delimiter, 1)[0], \
                          delimiter, fname)
        cmd = "sshpass -p root scp -o StrictHostKeyChecking=no %s@%s /tmp" % \
               (conf_options['v2x_lan_scp_userid'], \
                pkg)
        # LOG.debug("issuing '%s'" % cmd)
        if subprocess.call(cmd, shell=True):
            LOG.error("fail to scp %s from %s@%s" % (fname, \
                                                     conf_options['v2x_lan_scp_userid'], \
                                                     pkg))
            LOG.error("OTA abort due to scp fail")
            return
        # Use WiFi if applicable
	if not check_ping() == 0:
	    # Use GSM if applicable 
            if conf_options['gsm_enable']:
            	# Tear off gsm connection
            	self.gsm.stop()
        # Perform SW upgrade
	xc_led.all_leds(3)                    # all leds slow blink
        LOG.info("OTA auto upgrading ...")
        LOG.info("System will be reset after software upgrade ...")
        # directory prep
        cmd = "rm -fr ../backup/previous; mv -f ../backup/current ../backup/previous; \
               mkdir -p ../backup/current; \
               cp -f /tmp/%s /tmp/upgrade.ver ../backup/current" % fname
        # LOG.debug("issuing: " + cmd)
        if subprocess.call(cmd, shell=True):
            LOG.error("OTA software upgrade fail to directory prep")
            cmd = "rm -fr ../backup/current; mv -f ../backup/previous ../backup/current"
            # LOG.debug("issuing: " + cmd)
            if subprocess.call(cmd, shell=True):
                 LOG.error("Fail to restore directory !!!")
        # Store config
	cmd = "yes Y 2>/dev/null | openxc_save_config"
	if subprocess.call(cmd, shell=True):
	    LOG.error("Failed to save configuration files!  Aborting!")
	    return
	# upgrade now
        cmd = "cd /tmp; tar xvf %s; ./xc-upgrade.sh" % fname
        if subprocess.call(cmd, shell=True):
	    os.chdir("/root/OpenXCAccessory/common")
            LOG.info("OTA software upgrade fail")
            # Restore previous version
            ver, fname = subprocess.check_output("cat ../backup/previous/upgrade.ver", shell=True).split()
            LOG.info("Restoring previous software %s ..." % ver)
            cmd = "rm -fr ../backup/current; mv -f ../backup/previous ../backup/current; \
                   cp -f ../backup/current/%s /tmp; \
                   cd /tmp; tar xvf %s; ./xc-upgrade.sh" % (fname, fname)
            # LOG.debug("issuing: " + cmd)
            if subprocess.call(cmd, shell=True):
		os.chdir("/root/OpenXCAccessory/common")
                LOG.error("Fail to restore %s !!!" % ver)
	os.chdir("/root/OpenXCAccessory/common")
	# Restore Config
	cmd = "yes a 2>/dev/null | openxc_load_config"
	if subprocess.call(cmd, shell=True):
	    LOG.error("Failed to load configuration files!")
	# Reboot Machine
	cmd = "echo \"===>>> System will be rebooted in 3 seconds...\"; sleep 3; reboot"
	if subprocess.call(cmd, shell=True):
	    LOG.error("Unable to reboot!")
	return


def vi_auto_upgrade():
        ver_url = conf_options['web_scp_sw_latest_version_url']
        if ver_url is None or ver_url == 'None':
            return
        LOG.debug("OTA auto upgrade validation ..")
        # Use WiFi if applicable
        if not check_ping() == 0:
            # Use GSM if applicable 
            if conf_options['gsm_enable']:
            	if not self.gsm_instance():
                    LOG.error("OTA abort due to gsm_app instance fail")
                    return
            	if not self.gsm.start():
                    LOG.error("OTA abort due to gsm_app start fail")
                    # No need to move on without network connection
                    return 
        # Obtain latest version info
        cmd = "rm -fr /tmp/upgrade.ver; \
               scp -o StrictHostKeyChecking=no -i %s %s@%s /tmp/upgrade.ver" % \
                (conf_options['web_scp_pem'], \
                conf_options['web_scp_userid'], \
                ver_url)
        # LOG.debug("issuing '%s'" % cmd)
        if subprocess.call(cmd, shell=True):
            LOG.error("fail to scp upgrade.ver from %s@%s" % (conf_options['web_scp_userid'], \
                                                         ver_url))
            LOG.error("OTA abort due to scp fail")
            return
        ver, fname = subprocess.check_output("cat /tmp/upgrade.ver", shell=True).split()
        cver = xc_ver.get_version()
        LOG.debug("OTA latest=%s current=%s" % (ver, cver))
        if ver <= cver:
            return
        LOG.info("OTA auto upgrade for %s ..." % ver)
        # Obtain upgrading package
        if re.search(r'/', conf_options['web_scp_sw_latest_version_url'], re.M|re.I):
            delimiter = '/'
        else:
            delimiter = ':'
        pkg = "%s%s%s" % (conf_options['web_scp_sw_latest_version_url'].rsplit(delimiter, 1)[0], \
                          delimiter, fname)
        cmd = "scp -o StrictHostKeyChecking=no -i %s %s@%s /tmp" % \
               (conf_options['web_scp_pem'], \
                conf_options['web_scp_userid'], \
                pkg)
        # LOG.debug("issuing '%s'" % cmd)
        if subprocess.call(cmd, shell=True):
            LOG.error("fail to scp %s from %s@%s" % (fname, \
                                                     conf_options['web_scp_userid'], \
                                                     pkg))
            LOG.error("OTA abort due to scp fail")
            return
        # Use WiFi if applicable
	if not check_ping() == 0:
	    # Use GSM if applicable 
            if conf_options['gsm_enable']:
            	# Tear off gsm connection
            	self.gsm.stop()
        # Perform SW upgrade  
        xc_led.all_leds(3)                    # all leds slow blink
        LOG.info("OTA auto upgrading ...")
        LOG.info("System will be reset after software upgrade ...")
        # directory prep
        cmd = "rm -fr ../backup/previous; mv -f ../backup/current ../backup/previous; \
               mkdir -p ../backup/current; \
               cp -f /tmp/%s /tmp/upgrade.ver ../backup/current" % fname
        # LOG.debug("issuing: " + cmd)
        if subprocess.call(cmd, shell=True):
            LOG.error("OTA software upgrade fail to directory prep")
            cmd = "rm -fr ../backup/current; mv -f ../backup/previous ../backup/current"
            # LOG.debug("issuing: " + cmd)
            if subprocess.call(cmd, shell=True):
                 LOG.error("Fail to restore directory !!!")
        # Store config
	cmd = "yes Y 2>/dev/null | openxc_save_config"
	if subprocess.call(cmd, shell=True):
		LOG.error("Failed to save configuration files!  Aborting!")
		return
        # upgrade now
        cmd = "cd /tmp; tar xvf %s; ./xc-upgrade.sh" % fname
        if subprocess.call(cmd, shell=True):
            os.chdir("/root/OpenXCAccessory/common")
	    LOG.info("OTA software upgrade fail")
            # Restore previous version
            ver, fname = subprocess.check_output("cat ../backup/previous/upgrade.ver", shell=True).split()
            LOG.info("Restoring previous software %s ..." % ver)
            cmd = "rm -fr ../backup/current; mv -f ../backup/previous ../backup/current; \
                   cp -f ../backup/current/%s /tmp; \
                   cd /tmp; tar xvf %s; ./xc-upgrade.sh" % (fname, fname)
            # LOG.debug("issuing: " + cmd)
            if subprocess.call(cmd, shell=True):
		os.chdir("/root/OpenXCAccessory/common")
                LOG.error("Fail to restore %s !!!" % ver)
	os.chdir("/root/OpenXCAccessory/common")
	# Restore config
	cmd = "yes a 2>/dev/null | openxc_load_config"
	if subprocess.call(cmd, shell=True):
		LOG.error("Failed to load configuration files!")
	# Reboot Machine
        cmd = "echo \"===>>> System will be rebooted in 3 seconds...\"; sleep 3; reboot"
        if subprocess.call(cmd, shell=True):
                LOG.error("Unable to reboot !!!")
        return

def main():
	# Count args: If 1 try OTA; if 2 verify path is valid and a tarball
	if len(sys.argv) == 1:
		vi_auto_upgrade()
		return
	elif not len(sys.argv) == 2:
		LOG.info("Usage: ota_upgrade.py [path to tarball of form xc-upgrade-#.#.#.tar (if not included OTA upgrade will be used)]")
		return
	else:
		path = sys.argv[1]
		if (not os.path.isfile(path)) or (not path.endswith(".tar.gz")):
			LOG.error("Error: Invalid path specified!  Must be path to an xc-upgrade-#.#.#.tar.gz upgrade file.")
			return
		(dir, fname) = path.rsplit('/',1)
		ver = fname.split("-upgrade-")[1].split(".t")[0]
		# Untar the tarball into tmp
		cmd = "cd /tmp; tar zxvf %s; cp %s ." % (path, path)
		if subprocess.call(cmd, shell=True):
			LOG.error("Unable to untar and/or move tar.gz file!")
		cmd = "echo %s > /tmp/upgrade.ver; echo %s >> /tmp/upgrade.ver" % (ver, fname)
		if subprocess.call(cmd, shell=True):
			LOG.error("Unable to write to /tmp/upgrade.ver")
		cver = xc_ver.get_version()
		LOG.debug("Version to be installed=%s Current=%s" % (ver, cver))
		if ver <= cver:	# Do we need to check this if the update is being done manually?
			cont_choice = raw_input("The upgrade version (%s) is not newer than the current version (%s) continue with upgrade? (Y/n) " % (ver, cver))
			if not cont_choice == 'Y':
				LOG.info("Upgrade aborted by user")
				return
		xc_led.all_leds(3)	# Slow blink all LEDs
		LOG.info("Upgrading...")
		LOG.info("System will reset after software upgrade...")
		# Directory Prep
		cmd = "rm -fr ../backup/previous; mv -f ../backup/current ../backup/previous; \
		mkdir -p ../backup/current; \
		cp -f /tmp/%s /tmp/upgrade.ver ../backup/current" % fname
		if subprocess.call(cmd, shell=True):
			LOG.error("Software upgrade failed to prep the directory")
			cmd = "rm -fr ../backup/current; mv -f ../backup/previous ../backup/current"
			if subprocess.call(cmd, shell=True):
				LOG.error("Fail to restore directory !!!")
		# Store Config
		cmd = "openxc_save_config"
		config_save_res = subprocess.call(cmd, shell=True)
		if config_save_res == 1:
			LOG.error("Unable to save configuration files!")
			choice = raw_input("Press the enter key to continue or enter 'q' to quit: ")
			if choice.startswith('q'):
				LOG.info("Exiting per user request")
				return
		# Upgrade now
		cmd = "/tmp/xc-upgrade.sh"
		if subprocess.call(cmd, shell=True):
			os.chdir("/root/OpenXCAccessory/common")
			LOG.info("Software upgrade failed")
			# Restore previous version
			ver, fname = subprocess.check_output("cat ../backup/previous/upgrade.ver", shell=True).split()
			LOG.info("Restoring previous software %s ..." % ver)
			cmd = "rm -fr ../backup/current; mv -f ../backup/previous ../backup/current; \
			cp -f ../backup/current/%s /tmp; \
			cd /tmp; tar xvf %s; ./xc-upgrade.sh" % (fname, fname)
			if subprocess.call(cmd, shell=True):
				os.chdir("/root/OpenXCAccessory/common")
				LOG.error("Fail to restore %s !!!" % ver)
			os.chdir("/root/OpenXCAccessory/common")
		else:
			os.chdir("/root/OpenXCAccessory/common")
			LOG.info("Upgrade complete")
		# Restore config
		if not config_save_res == 1:
			if config_save_res == 2:
				LOG.info("NOTE: You chose not to save the config before updating, there may not be a config to restore or it may be old!")
			cmd = "openxc_load_config"
			if subprocess.call(cmd, shell=True) == 1:
				LOG.error("Failed to load configuration files !!!")
		# Reboot Machine
		cmd = "echo \"===>>> System will be rebooted in 3 seconds...\"; sleep 3; reboot"
		if subprocess.call(cmd, shell=True):
			LOG.error("Unable to reboot !!!")
		return

if __name__ == "__main__":
	main()
