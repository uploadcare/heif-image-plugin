import platform
import sysconfig

from setuptools import setup


options = {}
if (platform.python_implementation() == 'CPython'
        and not sysconfig.get_config_var('Py_GIL_DISABLED')):
    options['bdist_wheel'] = {'py_limited_api': 'cp39'}

setup(cffi_modules=['bindings/build.py:ffibuilder'], options=options)
