# coding=utf-8
import pytest


@pytest.fixture
def dns_sd():
    from pymachinetalk import dns_sd

    return dns_sd


@pytest.fixture
def sd():
    from pymachinetalk import dns_sd

    sd = dns_sd.ServiceDiscovery()
    return sd


def test_registeringServicesFromServiceContainerWorks(dns_sd, sd):
    service = dns_sd.Service()
    discoverable = dns_sd.ServiceContainer()
    discoverable.services.append(service)

    sd.register(discoverable)

    assert service in sd.services


def test_registeringServiceDirectlyWorks(dns_sd, sd):
    service = dns_sd.Service()

    sd.register(service)

    assert service in sd.services


def test_registeringAnythingElseFails(sd):
    item = object()

    try:
        sd.register(item)
    except TypeError:
        assert True

    assert item not in sd.services


def test_registeringWhenRunningThrowsError(dns_sd, sd):
    service = dns_sd.Service()

    def dummy():
        pass

    sd._start_discovery = dummy
    sd.start()

    try:
        sd.register(service)
    except RuntimeError:
        assert True

    assert service not in sd.services


def test_unregisteringServiceDirectlyWorks(dns_sd, sd):
    service = dns_sd.Service()
    sd.register(service)

    sd.unregister(service)

    assert service not in sd.services


def test_unregisteringServicesFromServiceContainerWorks(dns_sd, sd):
    service = dns_sd.Service()
    discoverable = dns_sd.ServiceContainer()
    discoverable.services.append(service)
    sd.register(discoverable)

    sd.unregister(discoverable)

    assert service not in sd.services


def test_unregisteringAnythingElseFails(sd):
    item = 34

    try:
        sd.unregister(item)
    except TypeError:
        assert True

    assert item not in sd.services


def test_unregisteringWhenRunningThrowsError(dns_sd, sd):
    service = dns_sd.Service()

    def dummy():
        pass

    sd._start_discovery = dummy
    sd.start()

    try:
        sd.unregister(service)
    except RuntimeError:
        assert True

    assert service not in sd.services


class ServiceInfoFactory(object):
    def create(
        self,
        base_type='machinekit',
        domain='local',
        sd_protocol='tcp',
        name='Hugo on Franz',
        service=b'halrcomp',
        uuid=b'12345678',
        host='127.0.0.1',
        protocol='tcp',
        port=12345,
        version=0,
        properties=None,
        server='127.0.0.1',
        address=None,
    ):
        from zeroconf import ServiceInfo

        typestring = '_%s._%s.%s.' % (base_type, sd_protocol, domain)
        dsn = b'%s://%s:%i' % (protocol.encode(), host.encode(), port)
        if properties is None:
            properties = {
                b'uuid': uuid,
                b'service': service,
                b'dsn': dsn,
                b'version': version,
            }
        return ServiceInfo(
            type_=typestring,
            name='%s %s.%s' % (name, host, typestring),
            properties=properties,
            address=(address or host).encode(),
            port=port,
            server=server,
        )


@pytest.fixture
def zeroconf(mocker):
    from zeroconf import Zeroconf

    service_info = ServiceInfoFactory().create()
    zeroconf_stub = mocker.stub(name='get_service_info')
    zeroconf_stub.return_value = service_info
    stub_object = Zeroconf()
    stub_object.get_service_info = zeroconf_stub
    return stub_object


@pytest.fixture
def zeroconf_without_service_info(mocker):
    from zeroconf import Zeroconf

    zeroconf_stub = mocker.stub(name='get_service_info')
    zeroconf_stub.return_value = None
    stub_object = Zeroconf()
    stub_object.get_service_info = zeroconf_stub
    return stub_object


def test_serviceDiscoveredUpdatesRegisteredServices(dns_sd, sd, zeroconf):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)

    sd.add_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )

    assert service.ready is True


def test_serviceDisappearedUpdatesRegisteredServices(dns_sd, sd, zeroconf):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)

    sd.add_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )
    sd.remove_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )

    assert service.ready is False


def test_stoppingServiceDiscoveryResetsAllServices(dns_sd, sd, zeroconf):
    service1 = dns_sd.Service(type_='halrcomp')
    sd.register(service1)
    service2 = dns_sd.Service(type_='halrcmd')
    sd.register(service2)
    sd.browser = object()  # dummy
    sd.add_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )

    sd.stop()

    assert service1.ready is False
    assert service2.ready is False


def test_serviceDiscoveredWithoutServiceInfoDoesNotUpdateRegisteredServices(
    dns_sd, sd, zeroconf_without_service_info
):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)

    sd.add_service(
        zeroconf_without_service_info,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )

    assert service.ready is False


def test_serviceDisappearedWithoutServiceInfoDoesNotUpdateRegisteredServices(
    dns_sd, sd, zeroconf_without_service_info
):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)
    service.ready = True

    sd.remove_service(
        zeroconf_without_service_info,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )

    assert service.ready is True


def test_serviceInfoSetsAllRelevantValuesOfService(dns_sd):
    service = dns_sd.Service(type_='halrcomp')
    service_info = ServiceInfoFactory().create(
        name='Foo on Bar',
        uuid=b'987654321',
        version=5,
        host='10.0.0.10',
        protocol='tcp',
        port=12456,
        server='sandybox.local',
    )

    service.add_service_info(service_info)

    assert service.uri == 'tcp://10.0.0.10:12456'
    assert service.name == service_info.name
    assert service.uuid == '987654321'
    assert service.version == 5
    assert service.host_name == 'sandybox.local'
    assert service.host_address == '10.0.0.10'


def test_serviceInfoResolvesLocalHostnameIfMatched(dns_sd):
    service = dns_sd.Service(type_='halrcomp')
    service_info = ServiceInfoFactory().create(
        host='sandybox.local',
        protocol='tcp',
        port=12456,
        server='sandybox.local',
        address='10.0.0.10',
    )

    service.add_service_info(service_info)

    assert service.uri == 'tcp://10.0.0.10:12456'


def test_serviceInfoRetursRawUriIfHostnameIsNotMatched(dns_sd):
    service = dns_sd.Service(type_='halrcomp')
    service_info = ServiceInfoFactory().create(
        host='thinkpad.local',
        protocol='tcp',
        port=12456,
        server='sandybox.local',
        address='10.0.0.10',
    )

    service.add_service_info(service_info)

    assert service.uri == 'tcp://thinkpad.local:12456'


def test_serviceInfoWithIncompleteValuesIsIgnoredByService(dns_sd):
    service = dns_sd.Service(type_='launcher')
    service_info = ServiceInfoFactory().create(properties={})

    service.add_service_info(service_info)

    assert service.uri == ''
    assert service.uuid == ''
    assert service.version == b''


def test_removingServiceInfoResetsAllRelevantValuesOfService(dns_sd):
    service = dns_sd.Service(type_='blahus')
    service_info = ServiceInfoFactory().create()
    service.add_service_info(service_info)

    service.remove_service_info(service_info)

    assert service.uri == ''
    assert service.name == ''
    assert service.uuid == ''
    assert service.version == 0
    assert service.host_name == ''
    assert service.host_address == ''


def test_clearingServiceInfosResetsValuesOfService(dns_sd):
    service = dns_sd.Service(type_='foobar')
    service.add_service_info(ServiceInfoFactory().create())
    service.add_service_info(ServiceInfoFactory().create())

    service.clear_service_infos()

    assert service.ready is False
    assert service.uri == ''


def test_settingReadyPropertyOfServiceTriggersCallback(dns_sd):
    cb_called = [False]

    def cb(_):
        cb_called[0] = True

    service = dns_sd.Service(type_='halrcomp')
    service.on_ready_changed.append(cb)
    service_info = ServiceInfoFactory().create()

    service.add_service_info(service_info)

    assert cb_called[0] is True


def test_discoverableAddingServiceWorks(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    service = dns_sd.Service(type_='foo')

    discoverable.add_service(service)

    assert service in discoverable.services


def test_discoverableAddingAnythingElseFails(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    item = object()

    try:
        discoverable.add_service(item)
        assert False
    except TypeError:
        assert True

    assert item not in discoverable.services


def test_discoverableRemovingServiceWorks(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    service = dns_sd.Service(type_='foo')

    discoverable.add_service(service)
    discoverable.remove_service(service)

    assert service not in discoverable.services


def test_discoverableRemvoingAnythingElseFails(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    item = object()

    try:
        discoverable.remove_service(item)
        assert False
    except TypeError:
        assert True

    assert item not in discoverable.services


def test_discoverableAllServicesReadySetServicesReady(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    service1 = dns_sd.Service(type_='foo')
    discoverable.add_service(service1)
    service2 = dns_sd.Service(type_='bar')
    discoverable.add_service(service2)

    service1.ready = True
    service2.ready = True

    assert discoverable.services_ready is True


def test_discoverableNotAllServicesReadyUnsetsServicesReady(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    service1 = dns_sd.Service(type_='foo')
    discoverable.add_service(service1)
    service2 = dns_sd.Service(type_='bar')
    discoverable.add_service(service2)

    service1.ready = True
    service2.ready = True
    service1.ready = False

    assert discoverable.services_ready is False


def test_discoverableServicesReadyChangedCallsCallback(dns_sd):
    cb_called = [False]

    def cb(_):
        cb_called[0] = True

    discoverable = dns_sd.ServiceContainer()
    discoverable.on_services_ready_changed.append(cb)

    discoverable.services_ready = True

    assert cb_called[0] is True


def test_serviceDiscoveryFilterAcceptCorrectUuid(dns_sd):
    service_info = ServiceInfoFactory().create(uuid=b'987654321')
    filter = dns_sd.ServiceDiscoveryFilter(txt_records={b'uuid': b'987654321'})

    assert filter.matches_service_info(service_info) is True


def test_serviceDiscoveryFilterRejectWrongUuid(dns_sd):
    service_info = ServiceInfoFactory().create(uuid=b'123456789')
    filter = dns_sd.ServiceDiscoveryFilter(txt_records={b'uuid': b'987654321'})

    assert filter.matches_service_info(service_info) is False


def test_serviceDiscoveryFilterAcceptFuzzyName(dns_sd):
    service_info = ServiceInfoFactory().create(name='Hello World')
    filter = dns_sd.ServiceDiscoveryFilter(name='Hello')

    assert filter.matches_service_info(service_info) is True


def test_serviceDiscoveryFilterAcceptExactMatchingName(dns_sd):
    service_info = ServiceInfoFactory().create(name='Foo')
    filter = dns_sd.ServiceDiscoveryFilter(name='Foo')

    assert filter.matches_service_info(service_info) is True


def test_serviceDiscoveryFilterRejectNonMatchingName(dns_sd):
    service_info = ServiceInfoFactory().create(name='Carolus Rex')
    filter = dns_sd.ServiceDiscoveryFilter(name='Adolfus Maximus')

    assert filter.matches_service_info(service_info) is False


def test_serviceDiscoveryFilterPassingWrongObjectFails(dns_sd):
    filter = dns_sd.ServiceDiscoveryFilter()

    try:
        filter.matches_service_info(object())
        assert False
    except TypeError:
        assert True


def test_serviceDiscoveryFiltersOutDiscoveredServiceWithWrongUuid(dns_sd, sd, zeroconf):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)
    sd.filter = dns_sd.ServiceDiscoveryFilter(txt_records={b'uuid': b'87654321'})

    sd.add_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Machinekit on MyBox 12.0.0.1._machinekit._tcp.local.',
    )

    assert service.ready is False


def test_serviceDiscoveryFiltersInDiscoveredServiceWithCorrectUuid(
    dns_sd, sd, zeroconf
):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)
    sd.filter = dns_sd.ServiceDiscoveryFilter(txt_records={b'uuid': b'12345678'})

    sd.add_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'SuperPrint 192.168.7.2._machinekit._tcp.local.',
    )
    assert service.ready is True


def test_serviceDiscoveryFiltersInDisappearedServiceWithCorrectUuid(
    dns_sd, sd, zeroconf
):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)
    sd.filter = dns_sd.ServiceDiscoveryFilter(txt_records={b'uuid': b'12345678'})

    sd.add_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'SuperPrint 192.168.7.2._machinekit._tcp.local.',
    )
    sd.remove_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'SuperPrint 192.168.7.2._machinekit._tcp.local.',
    )
    assert service.ready is False
