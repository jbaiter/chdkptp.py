import os
import subprocess

from setuptools.command.install import install as InstallCommand
from setuptools import setup

CHDKPTP_PATH = os.path.abspath(os.path.join('.', 'vendor', 'chdkptp'))


class CustomInstall(InstallCommand):
    def run(self):
        subprocess.check_call(['patch', '-d', CHDKPTP_PATH, '-i',
                               '../../chdkptp_module.diff', '-p', '1'])
        os.symlink(os.path.join(CHDKPTP_PATH, 'config-sample-linux.mk'),
                   os.path.join(CHDKPTP_PATH, 'config.mk'))
        subprocess.check_call(['make', '-C', CHDKPTP_PATH])
        InstallCommand.run(self)

setup(
    name='chdkptp.py',
    version="0.1",
    description=("Python bindings for chdkptp"),
    author="Johannes Baiter",
    url="http://github.com/jbaiter/chdkptp-py.git",
    author_email="johannes.baiter@gmail.com",
    license='GPL',
    packages=['chdkptp'],
    cmdclass={'install': CustomInstall}
)
