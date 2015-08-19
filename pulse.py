#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import ConfigParser
import copy
import logging
import optparse
import os
import socket
import time

import jenkins
import requests
import taskcluster

import lib
from lib.jsonfile import JSONFile
from lib.queues import (NormalizedBuildQueue,
                        TaskCompletedQueue,
                        )


class FirefoxAutomation:

    def __init__(self, configfile, pulse_authfile, debug, log_folder, logger,
                 build_message=None, update_message=None, display_only=False):

        self.config = JSONFile(configfile).read()
        self.debug = debug
        self.log_folder = log_folder
        self.logger = logger
        self.display_only = display_only
        self.build_message = build_message
        self.update_message = update_message

        self.jenkins = jenkins.Jenkins(self.config['jenkins']['url'],
                                       self.config['jenkins']['username'],
                                       self.config['jenkins']['password'])

        # When a local build message is used, return immediately
        if self.build_message:
            data = JSONFile(self.build_message).read()
            self.on_build(data)
            return

        # When a local update message is used, return immediately
        if self.update_message:
            data = JSONFile(self.update_message).read()
            self.on_update(data)
            return

        # Load Pulse Guardian authentication from config file
        if not os.path.exists(pulse_authfile):
            print 'Config file for Mozilla Pulse does not exist!'
            return

        pulse_cfgfile = ConfigParser.ConfigParser()
        pulse_cfgfile.read(pulse_authfile)

        auth = {}
        for key, value in pulse_cfgfile.items('pulse'):
            auth.update({key: value})

        name = 'queue/{user}/{host}/{type}'.format(user=auth['user'],
                                                   host=socket.getfqdn(),
                                                   type=self.config['pulse']['applabel'])
        queue_builds = NormalizedBuildQueue(name=name + '_build', callback=self.on_build,
                                            routing_key='build.#')
        queue_updates = TaskCompletedQueue(name=name + '_update', callback=self.on_update,
                                           routing_key='#.funsize-balrog.#')

        with lib.PulseConnection(userid=auth['user'], password=auth['password']) as connection:
            consumer = lib.PulseConsumer(connection)

            try:
                consumer.add_queue(queue_builds)
                consumer.add_queue(queue_updates)

                consumer.run()
            except KeyboardInterrupt:
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
                value = FirefoxAutomation.__dict__[method](self, value)

            parameters[entry] = value

        parameters['NODES'] = node

        return parameters

    def get_platform_identifier(self, platform):
        # Map to translate platform ids from RelEng
        platform_map = {'linux': 'linux',
                        'linux64': 'linux64',
                        'macosx': 'mac',
                        'macosx64': 'mac',
                        'win32': 'win32',
                        'win64': 'win64'}

        return platform_map[platform]

    def on_build(self, data, message=None):
        if message:
            data = data['payload']

        self.process_build(allowed_testruns=['functional', 'remote'],
                           platform=data['platform'],
                           product=data['product'].lower(),
                           version=data['version'],
                           branch=data['tree'],
                           locale=data['locale'],
                           buildid=data['buildid'],
                           revision=data['revision'],
                           tags=data['tags'],
                           status=data['status'],
                           json_data=data,
                           )

    def on_update(self, data, message=None):
        if message:
            # Retrieve manifest file with build information via TaskCluster
            queue = taskcluster.client.Queue()
            url = queue.buildUrl('getLatestArtifact', data['status']['taskId'],
                                 'public/env/manifest.json')
            response = requests.get(url)
            try:
                response.raise_for_status()
                data = response.json()
            finally:
                response.close()
        else:
            # Locally saved files will contain a single build only
            data = [data]

        for build_info in data:
            self.process_build(allowed_testruns=['update'],
                               platform=build_info['platform'],
                               product=build_info['appName'].lower(),
                               branch=build_info['branch'],
                               locale=build_info['locale'],
                               buildid=build_info['from_buildid'],
                               revision=build_info['revision'],
                               target_version=build_info['version'],
                               target_buildid=build_info['to_buildid'],
                               json_data=build_info,
                               )

    def process_build(self, allowed_testruns, platform, product, branch, locale,
                      buildid, revision, tags=None, version=None, status=0,
                      target_buildid=None, target_version=None, json_data=None):

        # Known failures from buildbot (http://mzl.la/1hlCYkw)
        results = ['success', 'warnings', 'failure', 'skipped', 'exception', 'retry']

        # if `--display-only` option has been specified only print build information and return
        if self.display_only:
            self.logger.info("Build properties:")
            for prop in sorted(json_data):
                self.logger.info("{:>24}:  {}".format(prop, json_data[prop]))
            return

        # Run checks to ensure it's a wanted build
        config = self.config['pulse']
        if config['platforms'] and platform not in config['platforms']:
            self.logger.debug('Cancel processing due to invalid platform: {}'.format(platform))
            return
        if config['products'] and product not in config['products']:
            self.logger.debug('Cancel processing due to invalid product: {}'.format(product))
            return
        if config['tags'] and tags is not None and not set(config['tags']).issubset(tags):
            self.logger.debug('Cancel processing due to invalid build tags: {}'.format(tags))
            return
        if config['trees'] and branch not in config['trees']:
            self.logger.debug('Cancel processing due to invalid branch: {}'.format(branch))
            return

        # If it's not a nightly or release branch, assume a project
        # branch based off from mozilla-central
        if 'mozilla-' not in branch:
            branch = 'project'

        # Get settings for the branch to run the tests for
        branch_config = self.config['testrun']['by_branch'].get(branch)
        if branch_config is None:
            self.logger.debug('Cancel processing due to missing branch config: {}'.format(branch))
            return

        # Check if locale is blacklisted
        if 'blacklist' in branch_config:
            if 'locales' in branch_config['blacklist'] and \
                    locale in branch_config['blacklist']['locales']:
                self.logger.debug('Cancel processing due to blacklisted locale: {}'.format(locale))
                return

        # Cancel processing if the locale is not white-listed. An empty array means
        # all locales will be processed.
        if 'locales' in branch_config and len(branch_config['locales']) and \
                locale not in branch_config['locales']:
            self.logger.debug('Cancel processing due to non-whitelisted locale: {}'.format(locale))
            return

        # Print build information to console
        log_data = (branch, buildid, locale, product, platform, revision,
                    version, target_buildid)
        if target_buildid:
            self.logger.info('{3} {6} ({1} => {7}, {5}, {2}, {4}) [{0}]'.format(*log_data))
        else:
            self.logger.info('{3} {6} ({1}, {5}, {2}, {4}) [{0}]'.format(*log_data))

        # Store build information to disk
        basename = '{1}_{3}_{2}_{4}_{0}.log'.format(*log_data)
        if target_buildid:
            basename = '{}_{}'.format(target_buildid, basename)
        filename = os.path.join(self.log_folder, branch, basename)

        try:
            if not os.path.exists(filename):
                JSONFile(filename).write(json_data)
        except Exception, e:
            self.logger.warning("Log file could not be written: {}.".format(str(e)))

        # Lets keep it after saving the log information so we might be able to
        # manually force-trigger those jobs in case of build failures.
        if status != 0:
            self.logger.info('Cancel processing due to broken build: {}'.format(results[status]))
            return

        platform_id = self.get_platform_identifier(platform)

        # Generate job data and queue up in Jenkins
        for testrun in branch_config['testruns']:
            if testrun not in allowed_testruns:
                continue

            # Fire off a build for each supported platform
            for node in branch_config['platforms'][platform_id]:
                job = '{}_{}'.format(branch, testrun)
                parameters = self.generate_job_parameters(testrun, node,
                                                          platform_id, json_data)

                self.logger.info('Triggering job "{}" on "{}"'.format(job, node))
                try:
                    self.jenkins.build_job(job, parameters)
                except Exception, e:
                    # For now simply discard and continue.
                    # Later we might want to implement a queuing mechanism.
                    self.logger.error('Cannot submit build request to "{}": {}'.format(
                        self.config['jenkins']['url'], str(e)))

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
    parser.add_option('--push-build-message',
                      dest='build_message',
                      help='Log file of a build message to process for Jenkins')
    parser.add_option('--push-update-message',
                      dest='update_message',
                      help='Log file of an update message to process for Jenkins')
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
                        format='%(asctime)s %(levelname)6s %(name)s: %(message)s',
                        datefmt='%Y-%m-%dT%H:%M:%SZ')
    logger = logging.getLogger('mozmill-ci')

    FirefoxAutomation(configfile=args[0],
                      pulse_authfile=options.pulse_authfile,
                      debug=options.debug,
                      log_folder=options.log_folder,
                      logger=logger,
                      build_message=options.build_message,
                      update_message=options.update_message,
                      display_only=options.display_only)


if __name__ == "__main__":
    main()
