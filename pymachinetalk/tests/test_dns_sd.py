# coding=utf-8
import socket

import pytest


@pytest.fixture
def dns_sd():
    from pymachinetalk import dns_sd

    return dns_sd


@pytest.fixture
def sd():
    from pymachinetalk import dns_sd

    return dns_sd.ServiceDiscovery()


def test_registering_services_from_service_container_works(dns_sd, sd):
    service = dns_sd.Service()
    discoverable = dns_sd.ServiceContainer()
    discoverable.services.append(service)

    sd.register(discoverable)

    assert service in sd.services


def test_registering_service_directly_works(dns_sd, sd):
    service = dns_sd.Service()

    sd.register(service)

    assert service in sd.services


def test_registering_anything_else_fails(sd):
    item = object()

    try:
        sd.register(item)
    except TypeError:
        assert True

    assert item not in sd.services


def test_registering_when_running_throws_error(dns_sd, sd):
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


def test_unregistering_service_directly_works(dns_sd, sd):
    service = dns_sd.Service()
    sd.register(service)

    sd.unregister(service)

    assert service not in sd.services


def test_unregistering_services_from_service_container_works(dns_sd, sd):
    service = dns_sd.Service()
    discoverable = dns_sd.ServiceContainer()
    discoverable.services.append(service)
    sd.register(discoverable)

    sd.unregister(discoverable)

    assert service not in sd.services


def test_unregistering_anything_else_fails(sd):
    item = 34

    try:
        sd.unregister(item)
    except TypeError:
        assert True

    assert item not in sd.services


def test_unregistering_when_running_throws_error(dns_sd, sd):
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
    @staticmethod
    def create(
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
            addresses=[socket.inet_aton(address or host)],
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


def test_service_discovered_updates_registered_services(dns_sd, sd, zeroconf):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)

    sd.add_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )

    assert service.ready is True


def test_service_updated_updates_registered_services(dns_sd, sd, zeroconf):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)

    sd.add_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )
    sd.update_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )

    assert service.ready is True


def test_service_disappeared_updates_registered_services(dns_sd, sd, zeroconf):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)

    zeroconf.get_service_info.return_value = ServiceInfoFactory.create(
        name='Foo on Bar', host='127.0.0.1'
    )
    sd.add_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )
    zeroconf.get_service_info.return_value = None
    sd.remove_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Foo on Bar 127.0.0.1._machinekit._tcp.local.',
    )

    assert service.ready is False


def test_stopping_service_discovery_resets_all_services(dns_sd, sd, zeroconf):
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


def test_service_discovered_without_service_info_does_not_update_registered_services(
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


def test_service_info_sets_all_relevant_values_of_service(dns_sd):
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


def test_service_info_updates_all_values_of_service(dns_sd):
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

    service_info = ServiceInfoFactory().create(
        name='Foo on Bar',
        uuid=b'nBzl8w',
        version=10,
        host='10.0.0.10',
        protocol='udp',
        port=12456,
        server='forest.local',
    )
    service.update_service_info(service_info)

    assert service.uri == 'udp://10.0.0.10:12456'
    assert service.name == service_info.name
    assert service.uuid == 'nBzl8w'
    assert service.version == 10
    assert service.host_name == 'forest.local'
    assert service.host_address == '10.0.0.10'


def test_service_info_resolves_local_hostname_if_matched(dns_sd):
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


def test_service_info_returs_raw_uri_if_hostname_is_not_matched(dns_sd):
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


def test_service_info_with_incomplete_values_is_ignored_by_service(dns_sd):
    service = dns_sd.Service(type_='launcher')
    service_info = ServiceInfoFactory().create(properties={})

    service.add_service_info(service_info)

    assert service.uri == ''
    assert service.uuid == ''
    assert service.version == b''


def test_removing_service_info_resets_all_relevant_values_of_service(dns_sd):
    service = dns_sd.Service(type_='blahus')
    service_info = ServiceInfoFactory().create()
    service.add_service_info(service_info)

    service.remove_service_info(service_info.name)

    assert service.uri == ''
    assert service.name == ''
    assert service.uuid == ''
    assert service.version == 0
    assert service.host_name == ''
    assert service.host_address == ''


def test_clearing_service_infos_resets_values_of_service(dns_sd):
    service = dns_sd.Service(type_='foobar')
    service.add_service_info(ServiceInfoFactory().create())
    service.add_service_info(ServiceInfoFactory().create())

    service.clear_service_infos()

    assert service.ready is False
    assert service.uri == ''


def test_setting_ready_property_of_service_triggers_callback(dns_sd):
    cb_called = [False]

    def cb(_):
        cb_called[0] = True

    service = dns_sd.Service(type_='halrcomp')
    service.on_ready_changed.append(cb)
    service_info = ServiceInfoFactory().create()

    service.add_service_info(service_info)

    assert cb_called[0] is True


def test_discoverable_adding_service_works(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    service = dns_sd.Service(type_='foo')

    discoverable.add_service(service)

    assert service in discoverable.services


def test_discoverable_adding_anything_else_fails(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    item = object()

    try:
        discoverable.add_service(item)
        assert False
    except TypeError:
        assert True

    assert item not in discoverable.services


def test_discoverable_removing_service_works(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    service = dns_sd.Service(type_='foo')

    discoverable.add_service(service)
    discoverable.remove_service(service)

    assert service not in discoverable.services


def test_discoverable_remvoing_anything_else_fails(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    item = object()

    try:
        discoverable.remove_service(item)
        assert False
    except TypeError:
        assert True

    assert item not in discoverable.services


def test_discoverable_all_services_ready_set_services_ready(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    service1 = dns_sd.Service(type_='foo')
    discoverable.add_service(service1)
    service2 = dns_sd.Service(type_='bar')
    discoverable.add_service(service2)

    service1.ready = True
    service2.ready = True

    assert discoverable.services_ready is True


def test_discoverable_not_all_services_ready_unsets_services_ready(dns_sd):
    discoverable = dns_sd.ServiceContainer()
    service1 = dns_sd.Service(type_='foo')
    discoverable.add_service(service1)
    service2 = dns_sd.Service(type_='bar')
    discoverable.add_service(service2)

    service1.ready = True
    service2.ready = True
    service1.ready = False

    assert discoverable.services_ready is False


def test_discoverable_services_ready_changed_calls_callback(dns_sd):
    cb_called = [False]

    def cb(_):
        cb_called[0] = True

    discoverable = dns_sd.ServiceContainer()
    discoverable.on_services_ready_changed.append(cb)

    discoverable.services_ready = True

    assert cb_called[0] is True


def test_service_discovery_filter_accept_correct_uuid(dns_sd):
    service_info = ServiceInfoFactory().create(uuid=b'987654321')
    filter_ = dns_sd.ServiceDiscoveryFilter(txt_records={b'uuid': b'987654321'})

    assert filter_.matches_service_info(service_info) is True


def test_service_discovery_filter_reject_wrong_uuid(dns_sd):
    service_info = ServiceInfoFactory().create(uuid=b'123456789')
    filter_ = dns_sd.ServiceDiscoveryFilter(txt_records={b'uuid': b'987654321'})

    assert filter_.matches_service_info(service_info) is False


def test_service_discovery_filter_accept_fuzzy_name(dns_sd):
    service_info = ServiceInfoFactory().create(name='Hello World')
    filter_ = dns_sd.ServiceDiscoveryFilter(name='Hello')

    assert filter_.matches_service_info(service_info) is True
    assert filter_.matches_name(service_info.name) is True


def test_service_discovery_filter_accept_exact_matching_name(dns_sd):
    service_info = ServiceInfoFactory().create(name='Foo')
    filter_ = dns_sd.ServiceDiscoveryFilter(name='Foo')

    assert filter_.matches_service_info(service_info) is True
    assert filter_.matches_name(service_info.name) is True


def test_service_discovery_filter_reject_non_matching_name(dns_sd):
    service_info = ServiceInfoFactory().create(name='Carolus Rex')
    filter_ = dns_sd.ServiceDiscoveryFilter(name='Adolfus Maximus')

    assert filter_.matches_service_info(service_info) is False
    assert filter_.matches_name(service_info.name) is False


def test_service_discovery_filter_passing_wrong_object_fails(dns_sd):
    filter_ = dns_sd.ServiceDiscoveryFilter()

    try:
        filter_.matches_service_info(object())
        assert False
    except TypeError:
        assert True


def test_service_discovery_filters_out_discovered_service_with_wrong_uuid(
    dns_sd, sd, zeroconf
):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)
    sd.filter = dns_sd.ServiceDiscoveryFilter(txt_records={b'uuid': b'87654321'})

    sd.add_service(
        zeroconf,
        '_machinekit._tcp.local.',
        'Machinekit on MyBox 12.0.0.1._machinekit._tcp.local.',
    )

    assert service.ready is False


def test_service_discovery_filters_in_discovered_service_with_correct_uuid(
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


def test_service_discovery_filters_in_disappeared_service_with_correct_uuid(
    dns_sd, sd, zeroconf
):
    service = dns_sd.Service(type_='halrcomp')
    sd.register(service)
    sd.filter = dns_sd.ServiceDiscoveryFilter(txt_records={b'uuid': b'12345678'})

    zeroconf.get_service_info.return_value = ServiceInfoFactory.create(
        name='SuperPrint', host='192.168.7.2'
    )
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
