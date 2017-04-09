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

def test_registeringServicesFromDiscoverableWorks(dns_sd, sd):
    service = dns_sd.Service()
    discoverable = dns_sd.Discoverable()
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

    assert not item in sd.services

@pytest.fixture
def zeroconf(mocker):
    from zeroconf import ServiceInfo, Zeroconf
    service_info = ServiceInfo(type_='_machinekit._tcp.local.',
                               name='Foo on Bar 127.0.0.1._machinekit._tcp.local.',
                               properties={'uuid': '12345678',
                                           'service': 'halrcomp',
                                           'uri': 'tcp://127.0.0.1:12345'})
    zeroconf_stub = mocker.stub(name='get_service_info')
    zeroconf_stub.return_value = service_info
    stub_object = Zeroconf()
    stub_object.get_service_info = zeroconf_stub
    return stub_object

def test_serviceDiscoveredUpdatesRegisteredServices(dns_sd, sd, zeroconf):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)

    sd.add_service(zeroconf, '_machinekit._tcp.local.', 'Foo on Bar 127.0.0.1._machinekit._tcp.local.')

    assert service.ready is True
    assert service.uri == 'tcp://127.0.0.1:12345'

def test_serviceDisappearedUpdatesRegistedServices(dns_sd, sd, zeroconf):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)

    sd.add_service(zeroconf, '_machinekit._tcp.local.', 'Foo on Bar 127.0.0.1._machinekit._tcp.local.')
    sd.remove_service(zeroconf, '_machinekit._tcp.local.', 'Foo on Bar 127.0.0.1._machinekit._tcp.local.')

    assert service.ready is False
