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

import lib
from lib.jsonfile import JSONFile
from lib.queues import (NormalizedBuildQueue,
                        FunsizeTaskCompletedQueue,
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

        # When a local build message is used, process it and return immediately
        if self.build_message:
            data = JSONFile(self.build_message).read()
            queue_builds.process_message(data, None)
            return

        # When a local update message is used, process it and return immediately
        if self.update_message:
            data = JSONFile(self.update_message).read()
            queue_updates.process_message(data, None)
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

    def generate_job_parameters(self, testrun, node, platform, tree, build_properties):
        # Create parameter map from Pulse to Jenkins properties
        map = self.config['pulse']['trees'][tree]['jenkins_parameter_map']
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

    def process_build(self, allowed_testruns, platform, product, branch, locale,
                      buildid, revision, tags=None, version=None, status=0,
                      target_buildid=None, target_version=None, json_data=None):

        # Known failures from buildbot (http://mzl.la/1hlCYkw)
        buildbot_results = ['success', 'warnings', 'failure', 'skipped', 'exception', 'retry']

        # if `--display-only` option has been specified, print update information only
        if self.display_only:
            self.logger.info("Properties:")
            for prop in sorted(json_data):
                self.logger.info("{:>24}:  {}".format(prop, json_data[prop]))
            return

        log_data = {
            'branch': branch,
            'buildid': buildid,
            'locale': locale,
            'product': product,
            'platform': platform,
            'revision': revision,
            'version': version,
            'target_buildid': target_buildid,
            'target_version': target_version,
        }

        # Bug 1176828 - Repack notifications for beta/release builds do not contain
        # a buildid. So use the timestamp if present as replacement
        if not log_data.get('buildid') and 'timestamp' in json_data:
            try:
                d = datetime.strptime(json_data['timestamp'], '%Y-%m-%dT%H:%M:%SZ')
                log_data['buildid'] = d.strftime('%Y%m%d%H%M')
            except:
                pass

        # Print build information to console
        if target_buildid:
            self.logger.info('{product} {target_version} ({buildid} => {target_buildid},'
                             ' {revision}, {locale}, {platform}) [{branch}]'.format(**log_data))
        else:
            self.logger.info('{product} {version} ({buildid}, {revision}, {locale},'
                             ' {platform}) [{branch}]'.format(**log_data))

        # Store build information to disk
        basename = '{buildid}_{product}_{locale}_{platform}.log'.format(**log_data)
        if target_buildid:
            basename = '{}_{}'.format(target_buildid, basename)
        filename = os.path.join(self.log_folder, branch, basename)

        try:
            if not os.path.exists(filename):
                JSONFile(filename).write(json_data)
        except Exception as e:
            self.logger.warning("Log file could not be written: {}.".format(str(e)))

        # Lets keep it after saving the log information so we might be able to
        # manually force-trigger those jobs in case of build failures.
        if status != 0:
            raise ValueError('Cancel processing due to broken build: {}'.
                             format(buildbot_results[status]))

        branch_config = self.config['jenkins']['jobs'][branch]
        platform_id = self.get_platform_identifier(platform)

        # Generate job data and queue up in Jenkins
        for testrun in branch_config['testruns']:
            if testrun not in allowed_testruns:
                continue

            # Fire off a build for each supported platform version
            for node in branch_config['nodes'][platform_id]:
                try:
                    job = '{}_{}'.format(branch, testrun)
                    parameters = self.generate_job_parameters(testrun,
                                                              node,
                                                              platform_id,
                                                              branch,
                                                              json_data)

                    self.logger.info('Triggering job "{}" on "{}"'.format(job, node))
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
                        format='%(asctime)s %(levelname)5s %(name)s: %(message)s',
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
