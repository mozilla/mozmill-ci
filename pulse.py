#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import copy
import json
import logging
import optparse
import os
import socket
import time

import jenkins
from pulsebuildmonitor import start_pulse_monitor


class NotFoundException(Exception):
    """Exception for a resource not being found (e.g. no logs)"""

    def __init__(self, message, location):
        self.location = location
        Exception.__init__(self, ': '.join([message, location]))


class JSONFile:

    def __init__(self, filename):
        self.filename = os.path.abspath(filename)

    def read(self):
        if not os.path.isfile(self.filename):
            raise NotFoundException('Specified file cannot be found.',
                                    self.filename)

        try:
            f = open(self.filename, 'r')
            return json.loads(f.read())
        finally:
            f.close()

    def write(self, data):
        folder = os.path.dirname(self.filename)
        if not os.path.exists(folder):
            os.makedirs(folder)

        try:
            f = open(self.filename, 'w')
            f.write(json.dumps(data))
        finally:
            f.close()


class Automation:

    def __init__(self, config, debug, log_folder, logger,
                 message=None, display_only=False):

        self.config = config
        self.debug = debug
        self.log_folder = log_folder
        self.logger = logger
        self.display_only = display_only
        self.test_message = message

        self.jenkins = jenkins.Jenkins(self.config['jenkins']['url'],
                                       self.config['jenkins']['username'],
                                       self.config['jenkins']['password'])

        # Whenever only a single message has to be sent we can return immediately
        if self.test_message:
            data = JSONFile(self.test_message).read()
            self.on_build(data)
            return

        # Make the consumer dependent to the host to prevent queue corruption by
        # other machines which are using the same queue name
        label = '%s|%s' % (self.config['pulse']['applabel'], socket.getfqdn())

        self.monitor = start_pulse_monitor(buildCallback=self.on_build,
                                           testCallback=None,
                                           pulseCallback=self.on_debug if self.debug else None,
                                           label=label,
                                           trees=self.config['pulse']['branches'],
                                           platforms=self.config['pulse']['platforms'],
                                           products=self.config['pulse']['products'],
                                           buildtypes=None,
                                           tests=None,
                                           buildtags=self.config['pulse']['tags'],
                                           logger=self.logger)

        try:
            while self.monitor.is_alive():
                self.monitor.join(1.0)
        except (KeyboardInterrupt, SystemExit):
            self.logger.info('Shutting down Pulse listener')

    def generate_job_parameters(self, testrun, node, platform, build_properties):
        # Create parameter map from Pulse to Jenkins properties
        map = self.config['testrun']['jenkins_parameter_map']
        parameter_map = copy.deepcopy(map['default'])
        if testrun in map:
            for key in map[testrun]:
                parameter_map[key] = map[testrun][key]

        # Create parameters and fill in values as given by the map
        parameters = {}
        for entry in parameter_map:
            value = None

            if 'key' in parameter_map[entry]:
                # A key means we have to retrieve a value from a dict
                value = build_properties.get(parameter_map[entry]['key'],
                                             parameter_map[entry].get('default'))
            elif 'value' in parameter_map[entry]:
                # A value means we have an hard-coded value
                value = parameter_map[entry]['value']

            if 'transform' in parameter_map[entry]:
                # A transformation method has to be called
                method = parameter_map[entry]['transform']
                value = Automation.__dict__[method](self, value)

            parameters[entry] = value

        # Add node and mozmill environment information
        parameters['NODES'] = node
        if testrun in ['endurance']:
            parameters['NODES'] = ' && '.join([parameters['NODES'], testrun])
        parameters['ENV_PLATFORM'] = self.get_mozmill_environment_platform(platform)

        return parameters

    def get_mozmill_environment_platform(self, platform):
        # Map to translate the platform to the Mozmill environment platform
        ENVIRONMENT_PLATFORM_MAP = {'linux': 'linux',
                                    'linux64': 'linux',
                                    'mac': 'mac',
                                    'win32': 'windows',
                                    'win64': 'windows'}

        return ENVIRONMENT_PLATFORM_MAP[platform]

    def get_platform_identifier(self, platform):
        # Map to translate platform ids from Pulse to Mozmill / Firefox
        PLATFORM_MAP = {'linux': 'linux',
                        'linux64': 'linux64',
                        'macosx': 'mac',
                        'macosx64': 'mac',
                        'win32': 'win32',
                        'win64': 'win64'}

        return PLATFORM_MAP[platform]

    def on_build(self, data):
        # From: http://hg.mozilla.org/build/buildbot/file/08b7c51d2962/master/buildbot/status/builder.py#l25
        results = ['success', 'warnings', 'failure', 'skipped', 'exception', 'retry']

        log_data = {'BRANCH': data['tree'],
                    'BUILD_ID': data['buildid'],
                    'KEY': data['key'],
                    'LOCALE': data['locale'],
                    'PRODUCT': data['product'],
                    'PLATFORM': data['platform'],
                    'STATUS': results[data['status']],
                    'TIMESTAMP': data['timestamp'],
                    'VERSION': data['version']}

        # Output build information to the console
        self.logger.info('%(TIMESTAMP)s - %(PRODUCT)s %(VERSION)s (%(BUILD_ID)s, %(LOCALE)s, %(PLATFORM)s) [%(BRANCH)s]' % log_data)

        # ... and store to disk
        basename = '%(BUILD_ID)s_%(PRODUCT)s_%(LOCALE)s_%(PLATFORM)s_%(KEY)s.log' % log_data
        filename = os.path.join(self.log_folder, data['tree'], basename)

        try:
            JSONFile(filename).write(data)
        except Exception, e:
            self.logger.warning("Log file could not be written: %s." % str(e))

        # if `--display-only` option has been specified only print build information and return
        if self.display_only:
            self.logger.info("Build properties:")
            for prop in data:
                self.logger.info("%20s:\t%s" % (prop, data[prop]))
            return

        # If the build process was broken we don't have to test this build
        if data['status'] != 0:
            self.logger.info('Cancel processing of broken build: status=%s' % results[data['status']])
            return

        # If it is not an official nightly or release branch, assume a project
        # branch based off from mozilla-central
        if not 'mozilla-' in data['tree']:
            data['branch'] = data['tree']
            data['tree'] = 'project'

        # Queue up jobs for the branch as given by config settings
        target_branch = self.config['testrun']['by_branch'][data['tree']]
        target_platform = self.get_platform_identifier(data['platform'])

        # Process the blacklist if one is present
        if 'blacklist' in target_branch:
            # Check the locale against the locales blacklist if one is present and
            # stop processing it if listed there
            if 'locales' in target_branch['blacklist'] and \
                    data['locale'] in target_branch['blacklist']['locales']:
                self.logger.info('Cancel processing of blacklisted locale: %s' % data['locale'])
                return

        # Process the whitelist if one is present
        if 'locales' in target_branch and \
                data['locale'] not in target_branch['locales']:
            self.logger.info('Cancel processing of non-whitelisted locale: %s' % data['locale'])
            return

        for testrun in target_branch['testruns']:
            # TODO: The following lines are pretty bad hacks,
            # so make those configurable in the json config (#209)
            # Do not run endurance tests for localized versions of Firefox
            if testrun in ['endurance'] and data['locale'] != 'en-US':
                continue

            # Do not run update tests for localized builds of Firefox, because
            # packaging is broken if nighlies get retriggered
            # See: https://bugzilla.mozilla.org/show_bug.cgi?id=858953
            if testrun in ['update'] and data['locale'] != 'en-US':
                continue

            # Do not run update tests if no previous build id is specified
            # See: https://bugzilla.mozilla.org/show_bug.cgi?id=714806#c17
            if testrun in ['update'] and not data['previous_buildid']:
                continue

            # Fire off a build for each supported platform
            for node in target_branch['platforms'][target_platform]:
                job = '%s_%s' % (data['tree'], testrun)
                parameters = self.generate_job_parameters(testrun, node,
                                                          target_platform, data)

                self.logger.info('Triggering job "%s" on "%s"' % (job, node))
                try:
                    self.jenkins.build_job(job, parameters)
                except Exception, e:
                    # For now simply discard and continue.
                    # Later we might want to implement a queuing mechanism.
                    self.logger.error('Jenkins instance at "%s" cannot be reached: %s' % (
                        self.config['jenkins']['url'],
                        str(e)))

            # Give Jenkins a bit of breath to process other threads
            time.sleep(2.5)

    def on_debug(self, data):
        """In debug mode save off all raw notifications"""

        basename = '%(BUILD_ID)s_%(PRODUCT)s_%(LOCALE)s_%(PLATFORM)s_%(KEY)s.log' % {
            'BUILD_ID': data['payload']['buildid'],
            'PRODUCT': data['payload']['product'],
            'LOCALE': data['payload']['locale'],
            'PLATFORM': data['payload']['platform'],
            'KEY': data['payload']['key']}
        filename = os.path.join('debug', data['payload']['tree'], basename)

        try:
            JSONFile(filename).write(data)
        except Exception, e:
            self.logger.warning("Debug file could not be written: %s." % str(e))


class DailyAutomation(Automation):

    def __init__(self, *args, **kwargs):
        Automation.__init__(self, *args, **kwargs)


def main():
    parser = optparse.OptionParser()
    parser.add_option('--debug',
                      dest='debug',
                      action='store_true',
                      default=False)
    parser.add_option('--log-folder',
                      dest='log_folder',
                      default='log',
                      help='Folder to write notification log files into')
    parser.add_option('--push-message',
                      dest='message',
                      help='Log file of a Pulse message to process for Jenkins')
    parser.add_option('--display-only',
                      dest='display_only',
                      action='store_true',
                      default=False,
                      help='Only display build properties and don\'t trigger jobs.')
    options, args = parser.parse_args()

    if not len(args):
        parser.error('A configuration file has to be passed in as first argument.')

    logging.Formatter.converter = time.gmtime
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s:%(name)s:%(message)s',
                        datefmt='%Y-%m-%dT%H:%M:%SZ')
    logger = logging.getLogger('automation')

    DailyAutomation(config=JSONFile(args[0]).read(),
                    debug=options.debug,
                    log_folder=options.log_folder,
                    logger=logger,
                    message=options.message,
                    display_only=options.display_only)

if __name__ == "__main__":
    main()
