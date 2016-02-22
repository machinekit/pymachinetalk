#/usr/bin/env python
import zmq
import gobject
import time
import sys
import threading
import argparse
from pymachinetalk.dns_sd import ServiceDiscovery
from machinetalk.protobuf.message_pb2 import Container
from machinetalk.protobuf.types_pb2 import *


class TestClass():
    def __init__(self, debug=False):
        self.debug = debug
        context = zmq.Context()
        context.linger = 0
        self.context = context

        services = ['launchercmd', 'halrcmd', 'command', 'config']
        for service in services:
            sd = ServiceDiscovery(service_type="_%s._sub._machinekit._tcp" % service)
            sd.on_discovered.append(self.service_discovered)
            sd.on_disappeared.append(self.service_disappeared)
            sd.start()
            #self.launcher_sd = launcher_sd

        self.tx = Container()
        self.rx = Container()

    def service_disappeared(self, data):
        if self.debug:
            print("disappeared %s %s" % (data.name))

    def service_discovered(self, data):
        if self.debug:
            print("discovered %s %s %s" % (data.name, data.dsn, data.uuid))
        self.send_broken(data.name, data.dsn)
        self.send_broker_msg(data.name, data.dsn)

    def send_broken(self, name, dsn):
        socket = self.context.socket(zmq.DEALER)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVTIMEO, 1000)
        if self.debug:
            print('connecting to %s' % dsn)
        socket.connect(dsn)
        bogus = 'random_string'
        if self.debug:
            print('sending bogus string %s' % bogus)
        socket.send(bogus)
        answer = ''
        try:
            answer = socket.recv()
        except zmq.error.Again as e:
            print('test failed, answer timed out %s' % name)
            return
        self.rx.ParseFromString(answer)
        if self.debug:
            print('received answer %s' % self.rx)
        if (self.rx.type == MT_ERROR):
            print('test successfull, %s handles broken messages' % name)
        else:
            print('test failed, %s does not handle broken messages' % name)

    def send_broker_msg(self, name, dsn):
        frontend = self.context.socket(zmq.ROUTER)
        backend = self.context.socket(zmq.DEALER)
        backend.setsockopt(zmq.IDENTITY, 'broker')
        socket = self.context.socket(zmq.DEALER)
        socket.setsockopt(zmq.IDENTITY, 'client')
        if self.debug:
            print('connecting backend to %s' % dsn)
        backend.connect(dsn)
        ipc = 'ipc://broker'
        if self.debug:
            print('connecting frontend to %s' % ipc)
        frontend.bind(ipc)
        if self.debug:
            print('connecting socket to %s' % ipc)
        socket.connect(ipc)
        if self.debug:
            print('sending ping via socket')
        self.tx.Clear()
        self.tx.type = MT_PING
        socket.send(self.tx.SerializeToString())
        if self.debug:
            print('receiving with broker:')
        recv = frontend.recv_multipart()
        if self.debug:
            print(recv)
            print('forwarding to host')
        backend.send_multipart(recv)
        if self.debug:
            print('receiving with backend:')
        recv = backend.recv_multipart()
        if self.debug:
            print(recv)
            print('sending data to frontend:')
        frontend.send_multipart(recv)
        if self.debug:
            print('receiving data with socket:')
        recv = socket.recv()
        self.rx.ParseFromString(recv)
        if self.debug:
            print(self.rx)
        if (self.rx.type == MT_PING_ACKNOWLEDGE):
            print('test successfull, %s handles multiple ids' % name)
        else:
            print('test failed, %s does not correctly handle multiple ids' % name)

def main():
    parser = argparse.ArgumentParser(description='tests Machinetalk RPC sockets behavior on broken messages and multiple ids')
    parser.add_argument('-d', '--debug', help='Enable debug mode', action='store_true')
    args = parser.parse_args()

    gobject.threads_init()  # important: initialize threads if gobject main loop is used
    testClass = TestClass(debug=args.debug)
    loop = gobject.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        loop.quit()

    print("stopping threads")
    # testClass.stop()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.1)

    print("threads stopped")
    sys.exit(0)

if __name__ == "__main__":
    main()
