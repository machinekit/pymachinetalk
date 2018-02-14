import pytest
import sys


@pytest.fixture
def application():
    from pymachinetalk import application
    return application


@pytest.fixture
def dns_sd():
    from pymachinetalk import dns_sd
    return dns_sd


@pytest.mark.skipif(sys.version_info >= (3, 0),
                    reason="Integration tests hang for some reason with Python3")
def test_application_integration(application, dns_sd):
    status = application.ApplicationStatus()
    command = application.ApplicationCommand()
    error = application.ApplicationError()
    appfile = application.ApplicationFile()

    sd = dns_sd.ServiceDiscovery()
    sd.register(status)
    sd.register(command)
    sd.register(error)
    sd.register(appfile)
