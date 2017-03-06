# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import ConfigParser
import copy
from datetime import datetime
import os
import socket
import time
import urlparse

import jenkins
import requests

from mozdownload import FactoryScraper
from mozdownload import errors as download_errors
from thclient import TreeherderClient

import lib
from lib.jsonfile import JSONFile
from lib.queues import (NormalizedBuildQueue,
                        FunsizeTaskCompletedQueue,
                        ReleaseTaskCompletedQueue,
                        )
import lib.tc as tc
import lib.treeherder as treeherder


class FirefoxAutomation:

    def __init__(self, configfile, authfile, treeherder_configfile, debug,
                 log_folder, logger, message=None, display_only=False):

        self.config = JSONFile(configfile).read()
        self.debug = debug
        self.log_folder = log_folder
        self.logger = logger
        self.display_only = display_only
        self.message = message
        self.treeherder_config = {}

        self.load_authentication_config(authfile)

        self.jenkins = jenkins.Jenkins(self.authentication['jenkins']['url'],
                                       self.authentication['jenkins']['user'],
                                       self.authentication['jenkins']['password'])

        # Setup Pulse listeners
        queue_name = 'queue/{user}/{host}/{type}'.format(user=self.authentication['pulse']['user'],
                                                         host=socket.getfqdn(),
                                                         type=self.config['pulse']['applabel'])

        # Load settings from the Treeherder config file
        with open(treeherder_configfile, 'r') as f:
            for line in f.readlines():
                if line.strip() and not line.startswith('#'):
                    key, value = line.strip().split('=')
                    self.treeherder_config.update({key: value})

        # Queue for build notifications
        queue_builds = NormalizedBuildQueue(
            name='{}_build'.format(queue_name),
            callback=self.process_build,
            pulse_config=self.config['pulse']
        )

        # Queue for release build notifications
        queue_release_builds = ReleaseTaskCompletedQueue(
            name='{}_build_release'.format(queue_name),
            callback=self.process_build,
            pulse_config=self.config['pulse'])

        # Queue for update notifications
        queue_updates = FunsizeTaskCompletedQueue(
            name='{}_update'.format(queue_name),
            callback=self.process_build,
            pulse_config=self.config['pulse']
        )

        # When a local message is used, process it and return immediately
        if self.message:
            data = JSONFile(self.message).read()

            # Check type of message and let it process by the correct queue
            if data.get('ACCEPTED_MAR_CHANNEL_IDS'):
                queue_updates.process_message(data, None)
            elif data.get('tags'):
                queue_builds.process_message(data, None)
            else:
                queue_release_builds.process_message(data, None)

            return

        with lib.PulseConnection(userid=self.authentication['pulse']['user'],
                                 password=self.authentication['pulse']['password']) as connection:
            consumer = lib.PulseConsumer(connection)

            try:
                consumer.add_queue(queue_builds)
                consumer.add_queue(queue_release_builds)
                consumer.add_queue(queue_updates)

                consumer.run()
            except KeyboardInterrupt:
                self.logger.info('Shutting down Pulse listener')

    def load_authentication_config(self, authfile):
        if not os.path.exists(authfile):
            raise IOError('Config file for authentications not found: {}'.
                          format(os.path.abspath(authfile)))

        config = ConfigParser.ConfigParser()
        config.read(authfile)

        auth = {}
        for section in config.sections():
            auth.setdefault(section, {})
            for key, value in config.items(section):
                auth[section].update({key: value})

        self.authentication = auth

    def generate_job_parameters(self, testrun, node, **pulse_properties):
        ci_system = node if node == 'taskcluster' else 'jenkins'

        # Create parameter map from Pulse to properties needed by the CI system
        pulse_props = self.config['pulse']['trees'][pulse_properties['tree']]
        map = pulse_props.get('{}_parameter_map'.format(ci_system), [])
        parameter_map = copy.deepcopy(map.get('default', {})) if map else []

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

    def query_file_url(self, properties, property_overrides=None):
        """Query for the specified build by using mozdownload.

        This method uses the properties as received via Mozilla Pulse to query
        the build via mozdownload. Use the property overrides to customize the
        query, e.g. different build or test package files.
        """
        property_overrides = property_overrides or {}

        if property_overrides.get('build_type'):
            build_type = property_overrides['build_type']
        else:
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

        # Update arguments with given overrides
        kwargs.update(property_overrides)

        self.logger.debug('Retrieve url for a {} file: {}'.format(build_type, kwargs))
        scraper = FactoryScraper(build_type, **kwargs)

        return scraper.url

    def get_installer_url(self, properties):
        """Get the installer URL if not given by the Pulse build notification.

        If the URL is not present it will be generated with mozdownload.
        """
        if properties.get('build_url'):
            build_url = properties['build_url']
        else:
            self.logger.info('Querying installer URL...')
            build_url = self.query_file_url(properties)

        self.logger.info('Found installer at: {}'.format(build_url))

        return build_url

    def get_mozharness_url(self, test_packages_url):
        """Get the mozharness URL which lays in the same folder as the test packages."""
        url = '{}/{}'.format(test_packages_url[:test_packages_url.rfind('/')], 'mozharness.zip')
        r = requests.head(url)
        if r.status_code != 200:
            url = None

        self.logger.info('Found mozharness URL at: {}'.format(url))

        return url

    def get_platform_identifier(self, platform):
        """Map to translate platform IDs from RelEng."""
        platform_map = {'macosx': 'mac',
                        'macosx64': 'mac',
                        }

        return platform_map.get(platform, platform)

    def get_test_packages_url(self, properties):
        """Return the URL of the test packages JSON file.

        In case of localized daily builds we can query the en-US build to get
        the URL, but for candidate builds we need the tinderbox build
        of the first parent changeset which was not checked-in by the release
        automation process (necessary until bug 1242035 is not fixed).
        """
        if properties.get('test_packages_url'):
            url = properties['test_packages_url']
        else:
            overrides = {
                'locale': 'en-US',
                'extension': 'test_packages.json',
            }

            # Use Treeherder to query for the next revision which has Tinderbox builds
            # available. We can use this revision to retrieve the test-packages URL.
            if properties['tree'].startswith('release-'):
                platform_map = {
                    'linux': {'build_platform': 'linux32'},
                    'linux64': {'build_platform': 'linux64'},
                    'macosx': {'build_os': 'mac', 'build_architecture': 'x86_64'},
                    'macosx64': {'build_os': 'mac', 'build_architecture': 'x86_64'},
                    'win32': {'build_os': 'win', 'build_architecture': 'x86'},
                    'win64': {'build_os': 'win', 'build_architecture': 'x86_64'},
                }

                self.logger.info('Querying tinderbox revision for {} build...'.format(
                                 properties['tree']))
                revision = properties['revision'][:12]

                client = TreeherderClient(server_url='https://treeherder.mozilla.org')
                resultsets = client.get_resultsets(properties['branch'],
                                                   tochange=revision,
                                                   count=50)

                # Retrieve the option hashes to filter for opt builds
                option_hash = None
                for key, values in client.get_option_collection_hash().iteritems():
                    for value in values:
                        if value['name'] == 'opt':
                            option_hash = key
                            break
                    if option_hash:
                        break

                # Set filters to speed-up querying jobs
                kwargs = {
                    'job_type_name': 'Build',
                    'exclusion_profile': False,
                    'option_collection_hash': option_hash,
                    'result': 'success',
                }
                kwargs.update(platform_map[properties['platform']])

                for resultset in resultsets:
                    kwargs.update({'result_set_id': resultset['id']})
                    jobs = client.get_jobs(properties['branch'], **kwargs)
                    if len(jobs):
                        revision = resultset['revision']
                        break

                self.logger.info('Found revision for tinderbox build: {}'.format(revision))

                overrides['build_type'] = 'tinderbox'
                overrides['revision'] = revision

            # For update tests we need the test package of the target build. That allows
            # us to add fallback code in case major parts of the ui are changing in Firefox.
            if properties.get('target_buildid'):
                overrides['build_id'] = properties['target_buildid']

            # The test package json file has a prefix with bug 1239808 fixed. Older builds need
            # a fallback to a prefix-less filename.
            try:
                self.logger.info('Querying test packages URL...')
                url = self.query_file_url(properties, property_overrides=overrides)
            except download_errors.NotFoundError:
                self.logger.info('URL not found. Querying not-prefixed test packages URL...')
                extension = overrides.pop('extension')
                build_url = self.query_file_url(properties, property_overrides=overrides)
                url = '{}/{}'.format(build_url[:build_url.rfind('/')], extension)
                r = requests.head(url)
                if r.status_code != 200:
                    url = None

            self.logger.info('Found test package URL at: {}'.format(url))

        return url

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
        :param test_packages_url: URL to the test_packages.json file.
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

        # Get some properties now so it hasn't to be done for each individual platform version
        pulse_properties['build_url'] = self.get_installer_url(pulse_properties)
        pulse_properties['test_packages_url'] = self.get_test_packages_url(pulse_properties)
        pulse_properties['mozharness_url'] = self.get_mozharness_url(
            pulse_properties['test_packages_url'])

        # Generate job data and queue up in Jenkins
        for testrun in tree_config['testruns']:
            if testrun not in pulse_properties['allowed_testruns']:
                continue

            # Fire off a build for each supported platform version
            for node in tree_config['nodes'][platform_id]:
                job = '{}_{}'.format(pulse_properties['tree'], testrun)
                self.logger.info('Triggering job "{}" on "{}"'.format(job, node))

                if node == 'taskcluster':
                    try:
                        th_url = self.treeherder_config['TREEHERDER_URL']

                        pulse_properties.update({
                            'revision_hash': treeherder.get_revision_hash(
                                urlparse.urlparse(th_url).netloc,
                                pulse_properties['branch'],
                                pulse_properties['revision']
                            ),
                            'treeherder_instance': self.treeherder_config['TREEHERDER_INSTANCE'],
                        })

                        # This includes a hard-coded channel name for now. Finally it has to be set
                        # via a web interface once we run tc tasks for mozilla-aurora, due to the
                        # 'auroratest' channel usage after branch merges.
                        extra_params = self.generate_job_parameters(testrun, node,
                                                                    **pulse_properties)
                        pulse_properties.update(extra_params)

                        fxui_worker = tc.FirefoxUIWorker(
                            client_id=self.treeherder_config['TASKCLUSTER_CLIENT_ID'],
                            authentication=self.treeherder_config['TASKCLUSTER_SECRET'],
                        )

                        payload = fxui_worker.generate_task_payload(testrun, pulse_properties)

                        if self.display_only:
                            self.logger.info('Payload: {}'.format(payload))
                            continue

                        task = fxui_worker.createTestTask(testrun, payload)
                        self.logger.info('Task has been created: {uri}{id}'.format(
                            uri=tc.URI_TASK_INSPECTOR,
                            id=task['status']['taskId'],
                        ))

                    except Exception:
                        # For now simply discard and continue.
                        # Later we might want to implement a queuing mechanism.
                        self.logger.exception('Cannot create task on Taskcluster')

                else:
                    try:
                        parameters = self.generate_job_parameters(testrun,
                                                                  node,
                                                                  **pulse_properties)

                        if self.display_only:
                            self.logger.info('Parameters: {}'.format(parameters))
                            continue

                        self.logger.debug('Parameters: {}'.format(parameters))

                        self.jenkins.build_job(job, parameters)

                    except Exception as exc:
                        # For now simply discard and continue.
                        # Later we might want to implement a queuing mechanism.
                        self.logger.exception('Cannot create job: "{}"'.format(exc.message))

            # Give Jenkins a bit of breath to process other threads
            time.sleep(2.5)
