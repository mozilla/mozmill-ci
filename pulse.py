#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import ConfigParser
import copy
from datetime import datetime
import logging
import optparse
import os
import socket
import time

import jenkins
from mozdownload import FactoryScraper

import lib
from lib.jsonfile import JSONFile
from lib.queues import (NormalizedBuildQueue,
                        FunsizeTaskCompletedQueue,
                        )


class FirefoxAutomation:

    def __init__(self, configfile, pulse_authfile, debug, log_folder, logger,
                 message=None, display_only=False):

        self.config = JSONFile(configfile).read()
        self.debug = debug
        self.log_folder = log_folder
        self.logger = logger
        self.display_only = display_only
        self.message = message

        self.jenkins = jenkins.Jenkins(self.config['jenkins']['url'],
                                       self.config['jenkins']['auth']['username'],
                                       self.config['jenkins']['auth']['password'])

        # Setup Pulse listeners
        self.load_pulse_config(pulse_authfile)
        queue_name = 'queue/{user}/{host}/{type}'.format(user=self.pulse_auth['user'],
                                                         host=socket.getfqdn(),
                                                         type=self.config['pulse']['applabel'])

        # Queue for build notifications
        queue_builds = NormalizedBuildQueue(name='{}_build'.format(queue_name),
                                            callback=self.process_build,
                                            pulse_config=self.config['pulse'])

        # Queue for update notifications
        queue_updates = FunsizeTaskCompletedQueue(name='{}_update'.format(queue_name),
                                                  callback=self.process_build,
                                                  pulse_config=self.config['pulse'])

        # When a local message is used, process it and return immediately
        if self.message:
            data = JSONFile(self.message).read()

            # Check type of message and let it process by the correct queue
            if data.get('ACCEPTED_MAR_CHANNEL_IDS'):
                queue_updates.process_message(data, None)
            else:
                queue_builds.process_message(data, None)
            return

        with lib.PulseConnection(userid=self.pulse_auth['user'],
                                 password=self.pulse_auth['password']) as connection:
            consumer = lib.PulseConsumer(connection)

            try:
                consumer.add_queue(queue_builds)
                consumer.add_queue(queue_updates)

                consumer.run()
            except KeyboardInterrupt:
                self.logger.info('Shutting down Pulse listener')

    def load_pulse_config(self, pulse_authfile):
        if not os.path.exists(pulse_authfile):
            raise IOError('Config file for Mozilla Pulse not found: {}'.
                          format(os.path.abspath(pulse_authfile)))

        pulse_cfgfile = ConfigParser.ConfigParser()
        pulse_cfgfile.read(pulse_authfile)

        auth = {}
        for key, value in pulse_cfgfile.items('pulse'):
            auth.update({key: value})

        self.pulse_auth = auth

    def generate_job_parameters(self, testrun, node, **pulse_properties):
        # Create parameter map from Pulse to Jenkins properties
        map = self.config['pulse']['trees'][pulse_properties['tree']]['jenkins_parameter_map']
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
                value = pulse_properties.get(parameter_map[entry]['key'],
                                             parameter_map[entry].get('default'))
            elif 'value' in parameter_map[entry]:
                # A value means we have an hard-coded value
                value = parameter_map[entry]['value']
            else:
                value = pulse_properties

            if 'transform' in parameter_map[entry]:
                # A transformation method has to be called
                method = parameter_map[entry]['transform']

                value = FirefoxAutomation.__dict__[method](self, value)

            parameters[entry] = value

        parameters['NODES'] = node

        return parameters

    def get_installer_url(self, properties):
        """Gets the installer URL if not given by the Pulse build notification.

        If the URL is not present it will be generated with mozdownload.
        """
        if properties.get('build_url'):
            return properties['build_url']

        # Update tests for beta/release builds would actually need a build_type
        # of 'release' instead of 'candidate' but we do not run the tests for
        # those builds.
        build_type = 'candidate' if 'release-' in properties['tree'] else 'daily'

        kwargs = {
            # General arguments for all types of builds
            'locale': properties['locale'],
            'platform': self.get_platform_identifier(properties['platform']),
            'retry_attempts': 5,
            'retry_delay': 30,

            # Arguments for daily builds
            'branch': properties.get('branch'),
            'build_id': properties.get('buildid'),

            # Arguments for candidate builds
            'build_number': properties.get('build_number'),
            'version': properties.get('version'),
        }

        self.logger.debug('Retrieve url for {} build: {}'.format(build_type, kwargs))
        scraper = FactoryScraper(build_type, **kwargs)

        return scraper.url

    def get_platform_identifier(self, platform):
        # Map to translate platform ids from RelEng
        platform_map = {'macosx': 'mac',
                        'macosx64': 'mac',
                        }

        return platform_map.get(platform, platform)

    def process_build(self, **pulse_properties):
        """Check properties and trigger a Jenkins build.

        :param allowed_test: Type of tests which are allowed to be run.
        :param platform: Platform to run the tests on.
        :param product: Name of the product (application).
        :param branch: Name of the branch the build was created off.
        :param locale: Locale of the build.
        :param buildid: ID of the build.
        :param revision: Revision (changeset) of the build.
        :param tags: Build classification tags (e.g. nightly, l10n).
        :param version: Version of the build.
        :param status: Build status from Buildbot (build notifications only).
        :param target_buildid: ID of the build after the upgrade (update notification only).
        :param target_version: Version of the build after the upgrade (update notification only).
        :param tree: Releng branch name the build was created off.
        :param raw_json: Raw pulse notification data

        """
        # Known failures from buildbot (http://mzl.la/1hlCYkw)
        buildbot_results = ['success', 'warnings', 'failure', 'skipped', 'exception', 'retry']

        # Bug 1176828 - Repack notifications for beta/release builds do not contain
        # a buildid. So use the timestamp if present as replacement
        if not pulse_properties['buildid'] and 'timestamp' in pulse_properties['raw_json']:
            try:
                d = datetime.strptime(pulse_properties['raw_json']['timestamp'],
                                      '%Y-%m-%dT%H:%M:%SZ')
                pulse_properties['buildid'] = d.strftime('%Y%m%d%H%M')
            except:
                pass

        # Print build information to console
        if pulse_properties.get('target_buildid'):
            self.logger.info('{product} {target_version} ({buildid} => {target_buildid},'
                             ' {revision}, {locale}, {platform}) [{branch}]'.format(
                                 **pulse_properties))
        else:
            self.logger.info('{product} {version} ({buildid}, {revision}, {locale},'
                             ' {platform}) [{branch}]'.format(**pulse_properties))

        # Store build information to disk
        basename = '{buildid}_{product}_{locale}_{platform}.log'.format(**pulse_properties)
        if pulse_properties.get('target_buildid'):
            basename = '{}_{}'.format(pulse_properties['target_buildid'], basename)
        filename = os.path.join(self.log_folder, pulse_properties['tree'], basename)

        try:
            if not os.path.exists(filename):
                JSONFile(filename).write(pulse_properties['raw_json'])
        except Exception as e:
            self.logger.warning("Log file could not be written: {}.".format(str(e)))

        # Lets keep it after saving the log information so we might be able to
        # manually force-trigger those jobs in case of build failures.
        if pulse_properties.get('status') and pulse_properties['status'] not in (0, 5):
            raise ValueError('Cancel processing due to broken build: {}'.
                             format(buildbot_results[pulse_properties['status']]))

        tree_config = self.config['jenkins']['jobs'][pulse_properties['tree']]
        platform_id = self.get_platform_identifier(pulse_properties['platform'])

        # Get the build URL now so it hasn't to be done for each individual build.
        pulse_properties['build_url'] = self.get_installer_url(pulse_properties)

        # Generate job data and queue up in Jenkins
        for testrun in tree_config['testruns']:
            if testrun not in pulse_properties['allowed_testruns']:
                continue

            # Fire off a build for each supported platform version
            for node in tree_config['nodes'][platform_id]:
                try:
                    job = '{}_{}'.format(pulse_properties['tree'], testrun)
                    parameters = self.generate_job_parameters(testrun,
                                                              node,
                                                              **pulse_properties)

                    self.logger.info('Triggering job "{}" on "{}"'.format(job, node))
                    if self.display_only:
                        self.logger.info('Parameters: {}'.format(parameters))
                        continue

                    self.logger.debug('Parameters: {}'.format(parameters))
                    self.jenkins.build_job(job, parameters)
                except Exception:
                    # For now simply discard and continue.
                    # Later we might want to implement a queuing mechanism.
                    self.logger.exception('Cannot create job at "{}"'.
                                          format(self.config['jenkins']['url']))

            # Give Jenkins a bit of breath to process other threads
            time.sleep(2.5)


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
    parser.add_option('--log-level',
                      dest='log_level',
                      default='INFO',
                      help='Logging level, default: %default')
    parser.add_option('--pulse-authfile',
                      dest='pulse_authfile',
                      default='.pulse_config.ini',
                      help='Path to the authentiation file for Pulse Guardian')
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
    logging.basicConfig(level=options.log_level,
                        format='%(asctime)s %(levelname)5s %(name)s: %(message)s',
                        datefmt='%Y-%m-%dT%H:%M:%SZ')
    logger = logging.getLogger('mozmill-ci')

    FirefoxAutomation(configfile=args[0],
                      pulse_authfile=options.pulse_authfile,
                      debug=options.debug,
                      log_folder=options.log_folder,
                      logger=logger,
                      message=options.message,
                      display_only=options.display_only)


if __name__ == "__main__":
    main()
