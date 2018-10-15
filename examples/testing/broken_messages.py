#!/usr/bin/env python
import zmq
import time
import sys
import threading
import argparse
from functools import partial
from pymachinetalk.dns_sd import Service, ServiceDiscovery
from machinetalk.protobuf.message_pb2 import Container
from machinetalk.protobuf.types_pb2 import *


class TestClass(object):
    def __init__(self, debug=False):
        self.debug = debug
        context = zmq.Context()
        context.linger = 0
        self.context = context

        self.sd = ServiceDiscovery()
        services = ['launchercmd', 'halrcmd', 'command', 'config']
        for name in services:
            service = Service(type_=name)
            self.sd.register(service)
            service.on_ready_changed.append(
                partial(self.service_ready, service=service)
            )

        self._tx = Container()
        self._rx = Container()

    def start(self):
        self.sd.start()

    def stop(self):
        self.sd.stop()

    def service_ready(self, ready, service):
        if ready:
            self.send_broken(service.name, service.uri)
            self.send_broker_msg(service.name, service.uri)

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
        self._rx.ParseFromString(answer)
        if self.debug:
            print('received answer %s' % self._rx)
        if self._rx.type == MT_ERROR:
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
        self._tx.Clear()
        self._tx.type = MT_PING
        socket.send(self._tx.SerializeToString())
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
        self._rx.ParseFromString(recv)
        if self.debug:
            print(self._rx)
        if self._rx.type == MT_PING_ACKNOWLEDGE:
            print('test successfull, %s handles multiple ids' % name)
        else:
            print('test failed, %s does not correctly handle multiple ids' % name)


def main():
    parser = argparse.ArgumentParser(
        description='tests Machinetalk RPC sockets behavior on broken messages and multiple ids'
    )
    parser.add_argument('-d', '--debug', help='Enable debug mode', action='store_true')
    args = parser.parse_args()

    test_class = TestClass(debug=args.debug)
    test_class.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    test_class.stop()

    print("stopping threads")
    # testClass.stop()

    # wait for all threads to terminate
    while threading.active_count() > 1:
        time.sleep(0.1)

    print("threads stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
