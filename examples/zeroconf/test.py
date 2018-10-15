#!/usr/bin/env python
from zeroconf import ServiceBrowser, Zeroconf
import time


class MyListener(object):
    def remove_service(self, zeroconf, type, name):
        print("Service %s removed" % (name,))

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        service = info.properties['service']
        uuid = info.properties['uuid']
        print('%s %s' % (service, uuid))
        # print("Service %s added, service info: %s, %s" % (name, service, uuid))


zeroconf = Zeroconf()
listener = MyListener()
browser = ServiceBrowser(zeroconf, "_machinekit._tcp.local.", listener)

try:
    while True:
        time.sleep(0.2)
except KeyboardInterrupt:
    pass
finally:
    zeroconf.close()
