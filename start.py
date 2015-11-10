#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))

JENKINS_VERSION = '1.580.3'
JENKINS_URL = 'http://mirrors.jenkins-ci.org/war-stable/%s/jenkins.war' % JENKINS_VERSION

JENKINS_ENV = os.path.join(HERE, 'jenkins-env', 'bin', 'activate_this.py')
JENKINS_WAR = os.path.join(HERE, 'war', 'jenkins-%s.war' % JENKINS_VERSION)


def start_jenkins():
    try:
        execfile(JENKINS_ENV, dict(__file__=JENKINS_ENV))
        print "Virtual environment activated successfully."
    except Exception as ex:
        print 'Could not activate virtual environment at "%s": %s.' % (JENKINS_ENV, str(ex))
        sys.exit(1)

    # do imports here because it requires the virtualenv to b activated
    from mozdownload import DirectScraper
    from mozprocess.processhandler import ProcessHandler

    # Download the Jenkins WAR file
    scraper = DirectScraper(url=JENKINS_URL, destination=JENKINS_WAR)
    scraper.download()

    # TODO: Start Jenkins as daemon
    print "Starting Jenkins"
    os.environ['JENKINS_HOME'] = os.path.join(HERE, 'jenkins-master')
    args = ['java', '-Xms2g', '-Xmx2g', '-XX:MaxPermSize=512M',
            '-Xincgc', '-jar', JENKINS_WAR]
    proc = ProcessHandler(args)
    proc.run()
    return proc


if __name__ == "__main__":
    proc = start_jenkins()
    sys.exit(proc.wait())
