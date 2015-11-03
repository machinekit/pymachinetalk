import sys
import avahi
import dbus
import pprint
import inspect
import avahi.ServiceTypeDatabase
import dbus.glib


class ServiceTypeDatabase:
    def __init__(self):
        self.pretty_name = avahi.ServiceTypeDatabase.ServiceTypeDatabase()

    def get_human_type(self, servicetype):
        if str(servicetype) in self.pretty_name:
            return self.pretty_name[servicetype]
        else:
            return servicetype


class ServiceDiscovery():
    def __init__(self, service_type, uuid='', interface='', debug=False):
        # callbacks
        self.on_discovered = []
        self.on_disappeared = []
        self.on_error = []

        self.server = None
        # Start Service Discovery
        self.debug = debug
        self.domain = ''
        self.service_type = service_type
        self.service_names = []  # used once discovered
        self.uuid = uuid
        self.interface = interface
        try:
            self.system_bus = dbus.SystemBus()
            self.system_bus.add_signal_receiver(self.avahi_dbus_connect_cb, "NameOwnerChanged", "org.freedesktop.DBus", arg0="org.freedesktop.Avahi")
        except dbus.DBusException, e:
            pprint.pprint(e)
            sys.exit(1)

        self.service_browsers = {}

    def start(self):
        self.start_service_discovery()

    def stop(self):
        self.stop_service_discovery()

    def avahi_dbus_connect_cb(self, a, connect, disconnect):
        if connect != "":
            print "We are disconnected from avahi-daemon"
            self.stop_service_discovery()
        else:
            print "We are connected to avahi-daemon"
            self.start_service_discovery()

    def siocgifname(self, interface):
        if interface <= 0:
            return "any"
        else:
            return self.server.GetNetworkInterfaceNameByIndex(interface)

    def service_resolved(self, interface, protocol, name, servicetype, domain, host, aprotocol, address, port, txt, flags):
        del aprotocol
        del flags
        stdb = ServiceTypeDatabase()
        h_type = stdb.get_human_type(servicetype)
        if self.debug:
            print "Service data for service '%s' of type '%s' (%s) in domain '%s' on %s.%i:" % (name, h_type, servicetype, domain, self.siocgifname(interface), protocol)
            print "\tHost %s (%s), port %i, TXT data: %s" % (host, address, port, avahi.txt_array_to_string_array(txt))

        txts = avahi.txt_array_to_string_array(txt)
        match = False
        dsn = None
        uuid = None
        for txt in txts:
            key, value = txt.split('=')
            if key == 'dsn':
                dsn = value
            elif key == 'uuid':
                uuid = value
                match = self.uuid == value
        match = match or (self.uuid == '')

        if match:
            self.service_names.append(name)
            if self.debug:
                print('discovered: %s %s %s' % (name, dsn, uuid))
            for func in self.on_discovered:
                if len(inspect.getargspec(func).args) == 4:  # pass uuid when callback wants it
                    func(name, dsn, uuid)
                else:
                    func(name, dsn)

    def print_error(self, err):
        if self.debug:
            print("SD Error: %s" % str(err))
        for func in self.on_error:
            func(str(err))

    def new_service(self, interface, protocol, name, servicetype, domain, flags):
        del flags
        if self.debug:
            print "Found service '%s' of type '%s' in domain '%s' on %s.%i." % (name, servicetype, domain, self.siocgifname(interface), protocol)

# this check is for local services
#        try:
#            if flags & avahi.LOOKUP_RESULT_LOCAL:
#                return
#        except dbus.DBusException:
#            pass

        self.server.ResolveService(interface, protocol, name, servicetype, domain, avahi.PROTO_INET, dbus.UInt32(0), reply_handler=self.service_resolved, error_handler=self.print_error)

    def remove_service(self, interface, protocol, name, servicetype, domain, flags):
        del flags
        if self.debug:
            print "Service '%s' of type '%s' in domain '%s' on %s.%i disappeared." % (name, servicetype, domain, self.siocgifname(interface), protocol)
        if name in self.service_names:
            self.service_names.remove(name)
            if self.debug:
                print("disappered: %s" % name)
            for func in self.on_disappeared:
                func(name)

    def add_service_type(self, interface, protocol, servicetype, domain):
        # Are we already browsing this domain for this type?
        if self.service_browsers in (interface, protocol, servicetype, domain):
            return

        if self.debug:
            print "Browsing for services of type '%s' in domain '%s' on %s.%i ..." % (servicetype, domain, self.siocgifname(interface), protocol)

        b = dbus.Interface(self.system_bus.get_object(avahi.DBUS_NAME,
                                                      self.server.ServiceBrowserNew(interface, protocol, servicetype, domain, dbus.UInt32(0))),
                           avahi.DBUS_INTERFACE_SERVICE_BROWSER)
        b.connect_to_signal('ItemNew', self.new_service)
        b.connect_to_signal('ItemRemove', self.remove_service)

        self.service_browsers[(interface, protocol, servicetype, domain)] = b

    def del_service_type(self, interface, protocol, servicetype, domain):

        service = (interface, protocol, servicetype, domain)
        if self.service_browsers not in service:
            return
        sb = self.service_browsers[service]
        try:
            sb.Free()
        except dbus.DBusException:
            pass
        del self.service_browsers[service]

    def start_service_discovery(self):
        if len(self.domain) != 0:
            print "domain not null %s" % (self.domain)
            print("Already Discovering")
            return
        try:
            self.server = dbus.Interface(self.system_bus.get_object(avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER),
                                         avahi.DBUS_INTERFACE_SERVER)
            self.domain = self.server.GetDomainName()
        except:
            print "Check that the Avahi daemon is running!"
            return

        if self.debug:
            print "Starting discovery"

        if self.interface == "":
            interface = avahi.IF_UNSPEC
        else:
            interface = self.server.GetNetworkInterfaceIndexByName(self.interface)
        protocol = avahi.PROTO_INET

        self.add_service_type(interface, protocol, self.service_type, self.domain)

    def stop_service_discovery(self):
        if len(self.domain) == 0:
            print "Discovery already stopped"
            return

        if self.debug:
            print "Discovery stopped"
