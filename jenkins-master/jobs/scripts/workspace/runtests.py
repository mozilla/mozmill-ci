#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import copy
import logging
import os
import subprocess
import sys

from buildbot import BuildExitCode
from config import config
from jenkins import JenkinsDefaultValueAction


here = os.path.dirname(os.path.abspath(__file__))

# Purge unwanted environment variables like credentials
ENV_VARS_TO_PURGE = [
    'AWS_BUCKET', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY',
    'TREEHERDER_URL', 'TREEHERDER_CLIENT_ID', 'TREEHERDER_SECRET',
]

logging.basicConfig(format='%(asctime)s %(levelname)s | %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger('mozmill-ci')
logger.setLevel(logging.INFO)


class BaseRunner(object):
    """Base class for different kinds of test runners."""

    def __init__(self, settings, **kwargs):
        """Creates new instance of the base runner class.

        :param settings: Settings for the Runner as retrieved from the config file.
        :param installer_url: URL of the build to download.
        :param repository: Name of the repository the build has been built from.
        :param test_packages_url: The URL of the test_packages.json file for the given build.
        """
        self.installer_url = kwargs['installer_url']
        self.repository = kwargs['repository']
        self.test_packages_url = kwargs['test_packages_url']
        self.settings = settings

    def query_args(self):
        """Returns all required and optional command line arguments."""
        args = [
            '--cfg', self.settings['harness_config'],
            '--installer-url', self.installer_url,
        ]

        if self.test_packages_url:
            args.extend(['--test-packages-url', self.test_packages_url])

        return args

    def run(self):
        """Executes the tests.

        It also ensures to save the return code of the subprocess to a file, which
        is used by the submission script to check the build status.

        """
        # Purge unwanted environment variables (Treeherder and AWS credentials)
        env = copy.copy(os.environ)
        for var in ENV_VARS_TO_PURGE:
            env.pop(var, None)

        # Set environment variable to let mozcrash save a copy of the minidump files
        env.update({'MINIDUMP_SAVE_PATH': os.path.join(here, 'minidumps')})

        command = [sys.executable, '-u',
                   os.path.join('mozharness', 'scripts', self.settings['harness_script'])]
        command.extend(self.query_args())

        logger.info('Calling command to execute tests: {}'.format(command))
        try:
            return subprocess.check_call(command, env=env)
        except subprocess.CalledProcessError as e:
            logger.exception('Failed to run external process')

            # Test for a valid index, and default to busted
            try:
                BuildExitCode[e.returncode]
                return e.returncode
            except IndexError:
                return BuildExitCode.busted


class FunctionalRunner(BaseRunner):
    """Runner class for functional ui tests."""

    def __init__(self, *args, **kwargs):
        """Creates new instance of the functional runner class."""
        BaseRunner.__init__(self, *args, **kwargs)

        if not kwargs['repository']:
            raise TypeError('Repository information have not been specified.')

    def query_args(self):
        """Returns additional required and optional command line arguments."""
        args = BaseRunner.query_args(self)
        args.extend(['--firefox-ui-branch', self.repository])

        return args


class UpdateRunner(BaseRunner):
    """Runner class for update tests."""

    def __init__(self, *args, **kwargs):
        """Creates new instance of the update runner class.

        :param allow_mar_channel: The allowed mar channels for the update.
        :param update_channel: The channel which is checked for available updates.
        :param update_target_version: The expected target version of the application.
        :param update_target_buildid: The expected target build id of the application.

        """
        BaseRunner.__init__(self, *args, **kwargs)

        if not kwargs['repository']:
            raise TypeError('Repository information have not been specified.')

        self.allow_mar_channel = kwargs['update_allow_mar_channel']
        self.channel = kwargs['update_channel']
        self.target_version = kwargs['update_target_version']
        self.target_buildid = kwargs['update_target_buildid']

    def query_args(self):
        """Returns all required and optional command line arguments."""
        args = BaseRunner.query_args(self)

        args.extend(['--firefox-ui-branch', self.repository])

        if self.allow_mar_channel:
            args.extend(['--update-allow-mar-channel', self.allow_mar_channel])
        if self.channel:
            args.extend(['--update-channel', self.channel])
        if self.target_version:
            args.extend(['--update-target-version', self.target_version])
        if self.target_buildid:
            args.extend(['--update-target-buildid', self.target_buildid])

        return args


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-type',
                        required=True,
                        choices=config['test_types'].keys(),
                        help='The type of tests to execute')
    parser.add_argument('--installer-url',
                        required=True,
                        help='The URL of the build installer.')
    parser.add_argument('--repository',
                        help='The repository name the build was created from.')
    parser.add_argument('--test-packages-url',
                        action=JenkinsDefaultValueAction,
                        help='The URL of the test_packages.json file for the given build.')

    update_group = parser.add_argument_group('Update Tests', 'Update test specific options')
    update_group.add_argument('--update-allow-mar-channel',
                              action=JenkinsDefaultValueAction,
                              help='The allowed mar channels for the update test')
    update_group.add_argument('--update-channel',
                              action=JenkinsDefaultValueAction,
                              help='The update channel to use for the update test')
    update_group.add_argument('--update-target-buildid',
                              action=JenkinsDefaultValueAction,
                              help='The expected BUILDID of the updated build')
    update_group.add_argument('--update-target-version',
                              action=JenkinsDefaultValueAction,
                              help='The expected version of the updated build')
    return parser.parse_args()


def main():
    logger.info('Run as: {}'.format(sys.argv))

    # Default exit code to `busted` state
    retval = BuildExitCode.busted

    # Maps the CLI test types to runner classes
    runner_map = {
        'functional': FunctionalRunner,
        'update': UpdateRunner,
    }

    try:
        kwargs = vars(parse_args())
        settings = config['test_types'].get(kwargs['test_type'])
        runner = runner_map[kwargs['test_type']](settings, **kwargs)
        retval = runner.run()

    finally:
        # Save exit code into file for further processing in report submission
        try:
            with file('retval.json', 'w') as f:
                f.write(str(retval))
        except OSError:
            logger.exception('Failed to save process return value')

if __name__ == '__main__':
    main()
