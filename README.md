# Machinetalk bindings for Python

  This repository contains Machinetalk bindings for
  Python. Machinetalk is the middleware for Machinekit the open source
  machine control software.

  For more information visit:
  http://machinekit.io
  https://github.com/machinekit/machinekit
  https://github.com/machinekit/machinetalk-protobuf

## Requirements

Pymachinetalk depends on the `machinetalk-protobuf`, `fysom` and `zmq` Python packages.

Note that you need a recent version of `fysom` (> 2.0) for pymachinetalk to work properly.

On Debian based distributions you can use the following commands:
```bash
# install Python ZMQ
sudo apt update
sudo apt install python-zmq

# install the rest from pip
sudo apt install python-pip
sudo pin install machinetalk-protobuf fysom
```

## Install

You can install pymachinetalk using the Python setuptools:

```bash
sudo python setup.py install
```
