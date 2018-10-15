# coding=utf-8
import pytest
import sys
from pymachinetalk import application
from pymachinetalk import dns_sd


@pytest.mark.skipif(
    sys.version_info >= (3, 0),
    reason="Integration tests hang for some reason with Python3",
)
def test_application_integration():
    status = application.ApplicationStatus()
    command = application.ApplicationCommand()
    error = application.ApplicationError()
    log = application.ApplicationLog()
    appfile = application.ApplicationFile()

    sd = dns_sd.ServiceDiscovery()
    sd.register(status)
    sd.register(command)
    sd.register(error)
    sd.register(log)
    sd.register(appfile)
