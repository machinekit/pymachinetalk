# coding=utf-8
from __future__ import unicode_literals
import re
import socket
from urllib.parse import urlparse

from zeroconf import ServiceBrowser, Zeroconf, ServiceInfo, ServiceListener


# see: https://stackoverflow.com/a/15831118/5768039
def ireplace(old, repl, text):
    return re.sub('(?i)' + re.escape(old), lambda m: repl, text)


class Service(object):
    def __init__(self, type_=''):
        self.type = type_
        self.domain = 'local'
        self.base_type = 'machinekit'
        self.protocol = 'tcp'
        self.name = ''
        self.uri = ''
        self.uuid = ''
        self.host_name = ''
        self.host_address = ''
        self.version = 0
        self._raw_uri = ''
        self._ready = False

        self.service_infos = []

        # callback
        self.on_ready_changed = []
        self.on_service_infos_updated = []

    @property
    def ready(self):
        return self._ready

    @ready.setter
    def ready(self, value):
        if value != self._ready:
            self._ready = value
            for cb in self.on_ready_changed:
                cb(value)

    @property
    def typestring(self):
        return '_%s._%s.%s.' % (self.base_type, self.protocol, self.domain)

    def matches_service_info(self, info):
        return (
            self.type == info.properties.get(b'service', b'').decode()
            and self.typestring in info.type
        )

    def __eq__(self, other):
        if isinstance(other, ServiceInfo):
            return self.name == other.name
        return False

    def add_service_info(self, info):
        self.service_infos.append(info)
        self._update()
        for cb in self.on_service_infos_updated:
            cb()

    def update_service_info(self, info):
        self._remove_service_info_entry(info.name)
        self.service_infos.append(info)
        self._update()
        for cb in self.on_service_infos_updated:
            cb()

    def remove_service_info(self, name):
        if self._remove_service_info_entry(name):
            self._update()
            for cb in self.on_service_infos_updated:
                cb()

    def clear_service_infos(self):
        self.service_infos = []
        self._update()

    def _remove_service_info_entry(self, name):
        updated = False
        for info in list(self.service_infos):
            if info.name == name:
                self.service_infos.remove(info)
                updated = True
                break
        return updated

    def _update(self):
        if any(self.service_infos):
            info = self.service_infos[0]
            self._set_all_values_from_service_info(info)
            self.ready = True
        else:
            self.ready = False
            self._init_all_values()

    def _set_all_values_from_service_info(self, info):
        self.name = info.name
        self._raw_uri = info.properties.get(b'dsn', b'').decode()
        self.uuid = info.properties.get(b'uuid', b'').decode()
        try:
            self.version = int(info.properties.get(b'version', b''))
        except ValueError:
            self.version = 0
        self.host_name = info.server
        try:
            self.host_address = str(socket.inet_ntoa(info.addresses[0]))
        except (OSError, socket.error):
            self.host_address = str(info.addresses[0])
        self._update_uri()

    def _update_uri(self):
        url = urlparse(self._raw_uri)
        host = url.hostname
        if (
            host is not None
            and self.host_name is not None
            and host.lower() in self.host_name.lower()
        ):  # hostname is in form .local. and host in .local
            netloc = url.netloc
            netloc = ireplace(host, self.host_address, netloc)
            new_url = url._replace(netloc=netloc)  # use resolved address
            self.uri = new_url.geturl()
        else:
            self.uri = self._raw_uri  # pass raw uri

    def _init_all_values(self):
        self.name = ''
        self.uri = ''
        self.uuid = ''
        self.host_name = ''
        self.host_address = ''
        self.version = 0


class ServiceDiscoveryFilter(object):
    def __init__(self, name='', txt_records=None):
        if txt_records is None:
            txt_records = {}
        self.name = name
        self.txt_records = txt_records

    def matches_service_info(self, info):
        if not isinstance(info, ServiceInfo):
            raise TypeError('must pass a ServiceInfo object')
        match = True
        if self.name not in info.name:
            match = False
        for name, value in self.txt_records.items():
            if info.properties[name.encode()] != value.encode():
                match = False
                break
        return match

    def matches_name(self, name):
        return self.name in name


class ServiceDiscovery(ServiceListener):
    def __init__(
        self,
        service_type='machinekit',
        filter_=ServiceDiscoveryFilter(),
        nameservers=None,
        lookup_interval=None,
    ):
        """Initialize the multicast or unicast DNS-SD service discovery instance.
        @param service_type DNS-SD type use for discovery, does not need to be
        changed for Machinekit. @param filter_ Optional filter can be used to look
        for specific instances. @param nameservers Pass one or more nameserver
        addresses to enabled unicast service discovery. @param lookup_interval How
        often the SD should send out service queries.
        """
        if nameservers is None:
            nameservers = []
        self.service_type = service_type
        self.filter = filter_
        self.nameservers = nameservers
        self.lookup_interval = lookup_interval

        self.is_ready = False
        self.services = []
        self._browsers = []
        self._zeroconfs = []

    def _start_discovery(self):
        self._zeroconfs = []
        self._browsers = []
        if any(self.nameservers):
            self._start_unicast_discovery()
        else:
            self._start_multicast_discovery()

    def _start_multicast_discovery(self):
        type_string = '_%s._tcp.local.' % self.service_type
        zeroconf = Zeroconf()
        self._zeroconfs.append(zeroconf)
        kwargs = {}
        if self.lookup_interval:
            kwargs['delay'] = self.lookup_interval
        self._browsers.append(ServiceBrowser(zeroconf, type_string, self, **kwargs))

    def _start_unicast_discovery(self):
        for service in self.services:
            type_string = '_%s._sub._%s._tcp.local.' % (service.type, self.service_type)
            zeroconf = Zeroconf(unicast=True)
            self._zeroconfs.append(zeroconf)
            for nameserver in self.nameservers:
                kwargs = {'addr': nameserver}
                if self.lookup_interval:
                    kwargs['delay'] = self.lookup_interval
                self._browsers.append(
                    ServiceBrowser(zeroconf, type_string, self, **kwargs)
                )

    def _stop_discovery(self):
        for zeroconf in self._zeroconfs:
            zeroconf.close()
        del self._zeroconfs[:]
        del self._browsers[:]
        for service in self.services:
            service.clear_service_infos()

    def remove_service(self, _zeroconf, _type, name):
        if not self.filter.matches_name(name):
            return
        for service in self.services:
            service.remove_service_info(name)

    def add_service(self, zeroconf, type_, name):
        info = zeroconf.get_service_info(type_, name)
        if info is None:
            return
        if not self.filter.matches_service_info(info):
            return
        for service in self.services:
            if service.matches_service_info(info):
                service.add_service_info(info)

    def update_service(self, zeroconf, type_, name):
        info = zeroconf.get_service_info(type_, name)
        if info is None:
            self.remove_service(zeroconf, type_, name)
            return
        if not self.filter.matches_service_info(info):
            return
        for service in self.services:
            if service.matches_service_info(info):
                service.update_service_info(info)

    @staticmethod
    def _verify_item_and_run(item, cmd):
        if isinstance(item, ServiceContainer):
            for service in item.services:
                cmd(service)
        elif isinstance(item, Service):
            cmd(item)
        else:
            raise TypeError('passed unregisterable item')

    def register(self, item):
        if self.is_ready:
            raise RuntimeError(
                'cannot register service when service discovery is already running'
            )
        self._verify_item_and_run(item, self.services.append)

    def unregister(self, item):
        if self.is_ready:
            raise RuntimeError(
                'cannot unregister service when service discovery is already running'
            )
        self._verify_item_and_run(item, self.services.remove)

    def start(self):
        if not self._browsers:
            self.is_ready = True
            self._start_discovery()

    def stop(self):
        self.is_ready = False
        self._stop_discovery()


class ServiceContainer(object):
    def __init__(self):
        self._services = []
        self._services_ready = False

        self.on_services_ready_changed = []

    @property
    def services(self):
        return self._services

    def add_service(self, service):
        if not isinstance(service, Service):
            raise TypeError('only Service is supported')
        self._services.append(service)
        service.on_ready_changed.append(self._update_services_ready)

    def remove_service(self, service):
        if not isinstance(service, Service):
            raise TypeError('only Service is supported')
        self._services.remove(service)
        service.on_ready_changed.remove(self._update_services_ready)

    @property
    def services_ready(self):
        return self._services_ready

    @services_ready.setter
    def services_ready(self, value):
        if value is not self._services_ready:
            self._services_ready = value
            for cb in self.on_services_ready_changed:
                cb(value)

    def _update_services_ready(self, _):
        ready = all(service.ready for service in self._services)
        self.services_ready = ready
