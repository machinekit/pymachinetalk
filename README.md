# Machinetalk bindings for Python
[![PyPI version](https://badge.fury.io/py/pymachinetalk.svg)](https://badge.fury.io/py/pymachinetalk)
[![Build Status](https://travis-ci.org/DiffSK/configobj.svg?branch=master)](https://travis-ci.org/machinekit/pymachinetalk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/machinekoder/speed-friending-matcher/blob/master/LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)

  This repository contains Machinetalk bindings for
  Python. Machinetalk is the middleware for Machinekit the open source
  machine control software.

  For more information visit:
  * http://machinekit.io
  * https://github.com/machinekit/machinekit
  * https://github.com/machinekit/machinetalk-protobuf

## Examples
You can find examples how to use pymachinetalk in [./examples/](./examples/)

### HAL Remote Quickstart
```python
import time
from pymachinetalk.dns_sd import ServiceDiscovery
import pymachinetalk.halremote as halremote

sd = ServiceDiscovery()

rcomp = halremote.RemoteComponent('anddemo', debug=False)
rcomp.newpin('button0', halremote.HAL_BIT, halremote.HAL_OUT)
rcomp.newpin('button1', halremote.HAL_BIT, halremote.HAL_OUT)
led_pin = rcomp.newpin('led', halremote.HAL_BIT, halremote.HAL_IN)
sd.register(rcomp)

sd.start()

try:
    while True:
        if rcomp.connected:
            print('LED status %s' %s str(led_pin.value)
        time.sleep(0.5)
except KeyboardInterrupt:
    pass

sd.stop()
```

## Install from PyPi
Pymachinetalk is available on [PyPI](https://pypi.python.org/pypi/pymachinetalk)

You can easily install it via pip:
```bash
sudo apt install python-pip
sudo pip install pymachinetalk
```

## Install from Source

### Requirements

Pymachinetalk depends on the `machinetalk-protobuf`, `fysom`, `zeroconf` and `pyzmq` Python packages.

Note that you need a recent version of `fysom` (> 2.0) for pymachinetalk to work properly.

On Debian based distributions you can use the following commands:
```bash
# install everything from pip
sudo apt install python-pip
pip install -e .[dev]
```

### Install

You can install pymachinetalk using the Python setuptools:

```bash
sudo python setup.py install
```

## TODO
* more and easier examples
* more testing
