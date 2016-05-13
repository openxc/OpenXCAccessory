#!/usr/bin/python
# $Rev: 230 $

from smbus import SMBus
import time

I2C_ADDRESS = 0x6b
I2C_VOLTAGE = 0x04
I2C_CURRENT = 0x03
I2C_WATCHDOG = 0x05
I2C_INPUT_SOURCE = 0x00

# open Linux device /dev/ic2-0
b = SMBus(0)

b.write_byte_data(I2C_ADDRESS,I2C_WATCHDOG,0x88)
b.write_byte_data(I2C_ADDRESS,I2C_CURRENT,0x10)
b.write_byte_data(I2C_ADDRESS,I2C_VOLTAGE,0xd6)
b.write_byte_data(I2C_ADDRESS,I2C_INPUT_SOURCE,0x07)
time.sleep(0.1)
