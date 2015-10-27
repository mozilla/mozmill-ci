#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import os
import shutil
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
venv_path = os.path.join(here, 'tests_venv')


# Create the test environment and activate it
# TODO remove once we make use of the mozharness script
import environment
command = ['python', os.path.join(here, 'firefox-ui-tests', 'create_venv.py'),
           '--strict', '--with-optional', venv_path]
print('Run command to create virtual environment for Firefox UI Tests: %s' % command)
subprocess.check_call(command)
environment.activate(venv_path)

# Can only be imported after the environment has been activated
import firefox_ui_tests
import firefox_puppeteer

from mozdownload import FactoryScraper

from config import config
from jenkins import JenkinsDefaultValueAction


class Runner(object):

    def run_tests(self, args):
        settings = config['test_types'][args.type]

        # In case the log folder does not exist yet we have to create it because
        # otherwise Marionette will fail for e.g. gecko.log (see bug 1211666)
        if settings['logs'].get('gecko.log'):
            try:
                os.makedirs(os.path.dirname(settings['logs']['gecko.log']))
            except OSError:
                print('Failed to create log folder for {}'.format(settings['logs']['gecko.log']))

        print('Downloading the installer: {}'.format(args.installer_url))
        scraper = FactoryScraper('direct',
                                 url=args.installer_url,
                                 retry_attempts=5,
                                 retry_delay=30,
                                 )
        installer_path = scraper.download()

        command = [
            'firefox-ui-update' if args.type == 'update' else 'firefox-ui-tests',
            '--installer', installer_path,
            '--workspace', os.getcwd(),
            '--log-tbpl', settings['logs']['tbpl.log'],
        ]

        if args.type == 'update':
            # Enable Gecko log to the console because the file would be overwritten
            # by the second update test
            command.extend(['--gecko-log', '-'])

            if args.update_channel:
                command.extend(['--update-channel', args.update_channel])
            if args.update_target_version:
                command.extend(['--update-target-version', args.update_target_version])
            if args.update_target_build_id:
                command.extend(['--update-target-buildid', args.update_target_build_id])

        elif args.type == 'functional':
            command.extend(['--gecko-log', settings['logs']['gecko.log']])

            manifests = [firefox_puppeteer.manifest, firefox_ui_tests.manifest_functional]
            command.extend(manifests)

        retval = 0

        print('Calling command to execute tests: {}'.format(command))
        retval = subprocess.call(command)

        # Save exit code into file for further processing in report submission
        try:
            with file('retval.txt', 'w') as f:
                f.write(str(retval))
        except OSError as e:
            print('Failed to save return value: {}'.format(e))

        # Delete http.log if tests were passing
        if not retval and settings['logs'].get('http.log'):
            shutil.rmtree(settings['logs']['http.log'], ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--type',
                        required=True,
                        choices=config['test_types'].keys(),
                        help='The type of tests to execute')
    parser.add_argument('--installer-url',
                        required=True,
                        help='The URL of the build installer.')

    update_group = parser.add_argument_group('update', 'Update test specific options')
    update_group.add_argument('--update-channel',
                              action=JenkinsDefaultValueAction,
                              help='The update channel to use for the update test')
    update_group.add_argument('--update-target-build-id',
                              action=JenkinsDefaultValueAction,
                              help='The expected BUILDID of the updated build')
    update_group.add_argument('--update-target-version',
                              action=JenkinsDefaultValueAction,
                              help='The expected version of the updated build')
    args = parser.parse_args()

    try:
        runner = Runner()
        runner.run_tests(args)
    except subprocess.CalledProcessError as e:
        sys.exit(e)

if __name__ == '__main__':
    main()
