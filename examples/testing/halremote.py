#!/usr/bin/env python

import time
import sys
import threading

from pymachinetalk.dns_sd import ServiceDiscovery
import pymachinetalk.halremote as halremote


class BasicClass(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True

    def run(self):
        timeout = 2.0

        sd = ServiceDiscovery()
        halrcomp = halremote.RemoteComponent('anddemo')
        halrcomp.newpin('button0', halremote.HAL_BIT, halremote.HAL_OUT)
        halrcomp.newpin('button1', halremote.HAL_BIT, halremote.HAL_OUT)
        halrcomp.newpin('led', halremote.HAL_BIT, halremote.HAL_IN)
        sd.register(halrcomp)

        sd.start()
        print('waiting for component connected')
        assert halrcomp.wait_connected(timeout)
        print('component connected')
        print('stopping service discovery')
        sd.stop()
        print('completed')


def main():
    basic = BasicClass()
    basic.start()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.1)

    print("threads stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
