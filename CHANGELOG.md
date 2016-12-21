# OpenXC-Accessory Dweet.io
Projects integrating Dweet.io with the Flextronics OpenXC Modem Embedded Software https://github.com/openxc/OpenXCAccessory

## Updated Files:

### [xc_vi.py](./common/xc_vi.py)
Updates to the OpenXC-Modem Vehicle Interface agent and unit test.  When `dweet_upload_enable` is activated in the configuration file (xc.conf), all other web upload functions via scp are disabled.  The dweet agent thread uses the VI Trace Log daemon to buffer incoming vehicle signals for transmission using the Dweet Python client library ("dweepy").

<strong>NOTE:</strong> Values set for `openxc_vi_trace_idle_duration` and `openxc_vi_trace_snapshot_duration` in xc.conf are overwritten to 1 second respectively in order to ensure payload size is compatible with the Dweet client.

### [xc.conf](./common/xc.conf#L148-L150)
Added the following user configuration settings 
* `dweet_upload_enable`
* `dweet_upload_interval`
* `dweet_thing_name`

When `dweet_upload_enable` is set to '1', the Web SCP VI Trace Upload functionality is disabled automatically.


### [Dweet Python Library - "Dweepy"](./common/dweepy/)
