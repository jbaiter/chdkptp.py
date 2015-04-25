import os
import subprocess

from setuptools.command.install import install as InstallCommand
from setuptools import setup

CHDKPTP_PATH = os.path.abspath(os.path.join('.', 'chdkptp', 'vendor',
                                            'chdkptp'))
CHDKPTP_PATCH = os.path.abspath(os.path.join('.', 'chdkptp_module.diff'))


class CustomInstall(InstallCommand):
    def run(self):
        subprocess.check_call(['patch', '-d', CHDKPTP_PATH, '-i',
                               CHDKPTP_PATCH, '-p', '1'])
        os.symlink(os.path.join(CHDKPTP_PATH, 'config-sample-linux.mk'),
                   os.path.join(CHDKPTP_PATH, 'config.mk'))
        subprocess.check_call(['make', '-C', CHDKPTP_PATH])
        InstallCommand.run(self)

setup(
    name='chdkptp.py',
    version="0.1.3",
    description=("Python bindings for chdkptp"),
    author="Johannes Baiter",
    url="http://github.com/jbaiter/chdkptp-py.git",
    author_email="johannes.baiter@gmail.com",
    license='GPL',
    packages=['chdkptp'],
    package_data={"chdkptp": ["vendor/chdkptp/chdkptp.so",
                              "vendor/chdkptp/lua/*.lua"]},
    install_requires=[
        "lupa >= 1.1",
    ],
    cmdclass={'install': CustomInstall}
)
