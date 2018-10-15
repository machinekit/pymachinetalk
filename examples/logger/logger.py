#!/usr/bin/env python
# coding=utf-8
import sys
import threading
import time

from pymachinetalk.dns_sd import ServiceDiscovery
from pymachinetalk import application


class Logger(object):
    def __init__(self, debug=False):
        self._sd = ServiceDiscovery()

        log = application.ApplicationLog(debug=debug)
        log.log_level = application.log.RTAPI_MSG_DBG
        log.on_message_received.append(self._on_log_message_received)

        self._sd.register(log)

    @staticmethod
    def _on_log_message_received(msg):
        print(msg)

    def start(self):
        self._sd.start()

    def stop(self):
        self._sd.stop()


def main():
    logger = Logger()

    print('starting')
    logger.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    print('stopping threads')
    logger.stop()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.1)

    print('threads stopped')
    sys.exit(0)


if __name__ == '__main__':
    main()
