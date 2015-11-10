#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
import tarfile
import urllib

from subprocess import check_call

import start


DIR_TEST_ENV = os.path.join('test', 'venv')
DIR_JENKINS_ENV = 'jenkins-env'
VERSION_VIRTUALENV = '13.1.2'


def check_patches():
    print 'Checking patches'
    check_call(['./test/check_patches.sh'])


class Jenkins(object):
    def __init__(self):
        self.proc = start.start_jenkins()

    def wait_for_started(self):
        # late imports because we need the jenkins virtualenv to be activated
        # (this is done in the constructor)
        import redo
        import requests

        session = requests.Session()

        def wait_for_jenkins():
            if not session.get('http://localhost:8080').status_code == 200:
                raise Exception('Jenkins did not start successfully.')

        redo.retry(wait_for_jenkins, sleeptime=0.5, jitter=0, sleepscale=1,
                   attempts=120)

    def kill(self):
        self.proc.kill()


class VirtualEnv(object):
    def __init__(self):
        if os.path.exists(DIR_TEST_ENV):
            print 'Using virtual environment in ', DIR_TEST_ENV
            return

        tar_fname = 'virtualenv-%s.tar.gz' % VERSION_VIRTUALENV
        print ('Creating a virtual environment (version %s) in %s'
               % (VERSION_VIRTUALENV, DIR_TEST_ENV))
        urllib.urlretrieve(
            ('https://pypi.python.org/packages/source/v/virtualenv/%s'
             % tar_fname),
            tar_fname
        )

        tar = tarfile.open(name=tar_fname)
        tar.extractall(path='.')
        check_call([sys.executable,
                    'virtualenv-%s/virtualenv.py' % VERSION_VIRTUALENV,
                    DIR_TEST_ENV])

    def activate(self):
        activate_this_file = os.path.join(DIR_TEST_ENV, 'bin',
                                          'activate_this.py')
        execfile(activate_this_file, dict(__file__=activate_this_file))

    def run(self, *args, **kwargs):
        check_call(args, **kwargs)


def run_tests():
    check_patches()

    if not os.path.exists(DIR_JENKINS_ENV):
        sys.exit('Jenkins env is not initialized. Please run "./setup.sh"')
    print 'Starting Jenkins'
    os.environ['JENKINS_HOME'] = 'jenkins-master'
    jenkins = Jenkins()
    try:
        jenkins.wait_for_started()
        venv = VirtualEnv()
        venv.activate()
        venv.run('pip', 'install', 'selenium')
        venv.run('python', 'test/configuration/save_config.py')
    finally:
        print 'Killing Jenkins'
        jenkins.kill()

    check_call(['git', '--no-pager', 'diff', '--exit-code'])


if __name__ == '__main__':
    this_dir = os.path.dirname(os.path.realpath(__file__))
    os.chdir(this_dir)
    run_tests()
