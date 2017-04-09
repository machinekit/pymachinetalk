from zeroconf import ServiceBrowser, Zeroconf, ServiceInfo


class Service(object):
    def __init__(self, type_=''):
        self.type = type_
        self.domain = ''
        self.base_type = ''
        self.protocol = ''
        self.name = ''
        self.uri = ''
        self.uuid = ''
        self.version = 0
        self.ready = False

        self.service_infos = []

    def matches_service_info(self, info):
        return self.type == info.properties['service']

    def __eq__(self, other):
        if isinstance(other, ServiceInfo):
            return self.name == other.name
        return False

    def add_service_info(self, info):
        self.service_infos.append(info)
        self._update()

    def remove_service_info(self, info):
        for info in self.service_infos:
            if self == info:
                self.service_infos.remove(info)
                break
        self._update()

    def _update(self):
        if len(self.service_infos) > 0:
            self.ready = True
            info = self.service_infos[0]
            self.name = info.name
            self.uri = info.properties['uri']
        else:
            self.ready = False


class ServiceDiscovery(object):
    def __init__(self, uuid='', service_type='machinekit'):
        self.service_type = service_type

        self.is_ready = False
        self.services = []
        self.browser = None

    def _start_discovery(self):
        zeroconf = Zeroconf()
        type_string = '_%s._tcp.local.' % self.service_type
        self.browser = ServiceBrowser(zeroconf, type_string, self)

    def _stop_discovery(self):
        pass

    def remove_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        for service in self.services:
            if service.matches_service_info(info):
                service.remove_service_info(info)

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        for service in self.services:
            if service.matches_service_info(info):
                service.add_service_info(info)

    def register(self, item):
        if isinstance(item, Discoverable):
            for service in item.services:
                self.services.append(service)
        elif isinstance(item, Service):
            self.services.append(item)
        else:
            raise TypeError('passed unregisterable item')

    def start(self):
        if not self.browser:
            self._start_discovery()

    def stop(self):
        if self.browser:
            self._stop_discovery()

    def ready(self):
        if not self.is_ready:
            self.is_ready = True
            self.start()


class Discoverable(object):
    def __init__(self):
        self.services = []
