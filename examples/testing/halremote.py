#/usr/bin/env python

import time
import sys
import gobject
import threading

from pymachinetalk.dns_sd import ServiceDiscovery
import pymachinetalk.halremote as halremote


class BasicClass(threading.Thread):
    def __init__(self, loop):
        threading.Thread.__init__(self)
        self.daemon = True
        self.loop = loop

    def run(self):
        timeout = 2.0

        launcher_sd = ServiceDiscovery(service_type="_launcher._sub._machinekit._tcp", debug=True)
        print('starting launcher service discovery')
        launcher_sd.start()
        assert launcher_sd.wait_discovered(timeout)
        data = launcher_sd.service_names.values()[0]
        print('launcher discovered %s %s' % (data.name, data.dsn))
        uuid = data.uuid
        print('uuid=%s' % uuid)

        halrcmd_sd = ServiceDiscovery(service_type="_halrcmd._sub._machinekit._tcp", uuid=uuid, debug=True)
        print('starting halrcmd service discovery')
        halrcmd_sd.start()
        assert halrcmd_sd.wait_discovered(timeout)
        data = halrcmd_sd.service_names.values()[0]
        print('halrcmd discovered %s %s' % (data.name, data.dsn))
        halrcmd_dsn = data.dsn

        halrcomp_sd = ServiceDiscovery(service_type="_halrcomp._sub._machinekit._tcp", uuid=uuid, debug=True)
        print('starting halrcomp service discovery')
        halrcomp_sd.start()
        assert halrcomp_sd.wait_discovered(timeout)
        data = halrcomp_sd.service_names.values()[0]
        print('halrcomp discovered %s %s' % (data.name, data.dsn))
        halrcomp_dsn = data.dsn

        halrcomp = halremote.RemoteComponent('anddemo')
        halrcomp.newpin('button0', halremote.HAL_BIT, halremote.HAL_OUT)
        halrcomp.newpin('button1', halremote.HAL_BIT, halremote.HAL_OUT)
        halrcomp.newpin('led', halremote.HAL_BIT, halremote.HAL_IN)
        #halrcomp.no_create = True
        halrcomp.halrcomp_uri = halrcomp_dsn
        halrcomp.halrcmd_uri = halrcmd_dsn

        halrcomp.ready()
        print('waiting for component connected')
        assert halrcomp.wait_connected()
        print('component connected')
        halrcomp.stop()

        self.loop.quit()


def main():
    gobject.threads_init()  # important: initialize threads if gobject main loop is used
    loop = gobject.MainLoop()
    basic = BasicClass(loop=loop)
    basic.start()
    try:
        loop.run()
    except KeyboardInterrupt:
        loop.quit()

    #print("stopping threads")
    #basic.stop()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.1)

    print("threads stopped")
    sys.exit(0)

if __name__ == "__main__":
    main()
