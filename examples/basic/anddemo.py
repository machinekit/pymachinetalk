#!/usr/bin/env python

import time
import sys
import gobject
import threading

from pymachinetalk.dns_sd import ServiceDiscovery
import pymachinetalk.halremote as halremote


class BasicClass():
    def __init__(self):
        launcher_sd = ServiceDiscovery(service_type="_launcher._sub._machinekit._tcp")
        launcher_sd.on_discovered.append(self.service_discovered)
        launcher_sd.on_disappeared.append(self.service_disappeared)
        launcher_sd.start()
        self.launcher_sd = launcher_sd

        self.halrcompReady = False
        self.halrcmdReady = False
        halrcomp = halremote.RemoteComponent('anddemo')
        halrcomp.newpin('button0', halremote.HAL_BIT, halremote.HAL_OUT)
        halrcomp.newpin('button1', halremote.HAL_BIT, halremote.HAL_OUT)
        halrcomp.newpin('led', halremote.HAL_BIT, halremote.HAL_IN)
        halrcomp.no_create = True
        self.halrcomp = halrcomp

    def start_sd(self, uuid):
        halrcmd_sd = ServiceDiscovery(service_type="_halrcmd._sub._machinekit._tcp", uuid=uuid)
        halrcmd_sd.on_discovered.append(self.halrcmd_discovered)
        halrcmd_sd.start()
        #halrcmd_sd.disappered_callback = disappeared
        #self.halrcmd_sd = halrcmd_sd

        halrcomp_sd = ServiceDiscovery(service_type="_halrcomp._sub._machinekit._tcp", uuid=uuid)
        halrcomp_sd.on_discovered.append(self.halrcomp_discovered)
        halrcomp_sd.start()
        #self.harcomp_sd = halrcomp_sd

    def service_disappeared(self, data):
        print("disappeared %s %s" % (data.name))

    def service_discovered(self, data):
        print("discovered %s %s %s" % (data.name, data.dsn, data.uuid))
        self.start_sd(data.uuid)

    def halrcmd_discovered(self, data):
        print("discovered %s %s" % (data.name, data.dsn))
        self.halrcomp.halrcmd_uri = data.dsn
        self.halrcmdReady = True
        if self.halrcompReady:
            self.start_halrcomp()

    def halrcomp_discovered(self, data):
        print("discovered %s %s" % (data.name, data.dsn))
        self.halrcomp.halrcomp_uri = data.dsn
        self.halrcompReady = True
        if self.halrcmdReady:
            self.start_halrcomp()

    def start_halrcomp(self):
        print('connecting rcomp %s' % self.halrcomp.name)
        self.halrcomp.ready()

    def stop(self):
        self.halrcomp.stop()


def main():
    gobject.threads_init()  # important: initialize threads if gobject main loop is used
    basic = BasicClass()
    loop = gobject.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        loop.quit()

    print("stopping threads")
    basic.stop()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.1)

    print("threads stopped")
    sys.exit(0)

if __name__ == "__main__":
    main()
