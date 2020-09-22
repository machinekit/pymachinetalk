#!/usr/bin/env python
# coding=utf-8

import sys

# We must use setuptools, not distutils, because we need to use the
# namespace_packages option for the "google" package.
try:
    from setuptools import setup, Extension, find_packages
except ImportError:
    try:
        from ez_setup import use_setuptools

        use_setuptools()
        from setuptools import setup, Extension, find_packages
    except ImportError:
        sys.stderr.write(
            "Could not import setuptools; make sure you have setuptools or "
            "ez_setup installed.\n"
        )
        raise

from distutils.command.clean import clean
from distutils.command.build_py import build_py_2to3 as build_py

requirements = ['pyzmq', 'protobuf', 'machinetalk-protobuf', 'fysom', 'zeroconf']


if __name__ == '__main__':
    setup(
        name="pymachinetalk",
        version="0.13.3",
        description="Python bindings for Machinetalk",
        author="Alexander Roessler",
        author_email="alex@machinekoder.com",
        url="https://github.com/machinekit/pymachinetalk",
        namespace_packages=['pymachinetalk'],
        packages=find_packages(),
        install_requires=requirements,
        extras_require={'dev': ['pytest', 'pytest-mock', 'pytest-pep8', 'pytest-cov']},
        cmdclass={'clean': clean, 'build_py': build_py},
    )
