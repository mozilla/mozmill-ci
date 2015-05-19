#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import glob
import optparse
import os
import subprocess
import sys


here = os.path.dirname(os.path.abspath(__file__))


class Runner(object):

    def __init__(self, venv_path):
        self.venv_path = venv_path
        self.build_path = os.path.join(here, 'build')

        os.chdir(here)
        self.activate_venv()

    def activate_venv(self):
        if not os.path.exists(self.venv_path):
            os.chdir(os.path.join(here, 'firefox-ui-tests'))
            subprocess.check_call(['python', 'create_venv.py',
                                   '--with-optional-packages',
                                   self.venv_path
                                   ])
            os.chdir(here)

        dir = 'Scripts' if sys.platform == 'win32' else 'bin'
        env_activate_file = os.path.join(self.venv_path, dir, 'activate_this.py')

        # Activate the environment and set the VIRTUAL_ENV os variable
        execfile(env_activate_file, dict(__file__=env_activate_file))
        os.environ['VIRTUAL_ENV'] = self.venv_path

    def download_build(self, options, args):
        command = ['mozdownload',
                   '--destination=%s' % self.build_path,
                   '--type=%s' % options.build_type,
                   '--branch=%s' % options.branch,
                   '--build-id=%s' % options.build_id,
                   '--locale=%s' % options.build_locale,
                   '--platform=%s' % options.platform,
                   ]
        subprocess.check_call(command)

    def run_tests(self, options, args):
        # Download the build under test
        self.download_build(options, args)

        import firefox_ui_tests
        import firefox_puppeteer

        command = [
            'firefox-ui-update' if options.type == 'update' else 'firefox-ui-tests',
            '--installer=%s' % glob.glob(os.path.join(self.build_path, '*firefox-*'))[0],
            '--log-xunit=report.xml',  # Enable XUnit reporting for Jenkins result analysis
            '--log-html=report.html',  # Enable HTML reports with screenshots
        ]

        if options.type == 'update':
            # Ensure to enable Gecko log output in the console because the file gets
            # overwritten with the second update run
            command.append('--gecko-log=-')

            if options.update_channel:
                command.append('--update-channel=%s' % options.update_channel)
            if options.update_target_version:
                command.append('--update-target-version=%s' % options.update_target_version)
            if options.update_target_build_id:
                command.append('--update-target-buildid=%s' % options.update_target_build_id)

        elif options.type == 'functional':
            manifests = [firefox_puppeteer.manifest, firefox_ui_tests.manifest_functional]
            command.extend(manifests)

        elif options.type == 'remote':
            manifests = [firefox_ui_tests.manifest_remote]
            command.extend(manifests)

        print 'Execute tests: %s' % command
        subprocess.check_call(command)


def main():
    parser = optparse.OptionParser()
    parser.add_option('--branch',
                      dest='branch',
                      help='The branch of the Github repository to use')
    parser.add_option('--type',
                      dest='type',
                      choices=['functional', 'remote', 'update'],
                      help='The type of tests to execute')
    parser.add_option('--platform',
                      dest='platform',
                      help='The platform identifier where the build gets executed')

    build_options = optparse.OptionGroup(parser, "Build specific options")
    build_options.add_option('--build-date',
                             dest='build_date',
                             help='The date when the build has been created.')
    build_options.add_option('--build-id',
                             dest='build_id',
                             help='The BUILDID of the build to test')
    build_options.add_option('--build-locale',
                             dest='build_locale',
                             default='en-US',
                             help='The locale of the build. Default: %default')
    build_options.add_option('--build-type',
                             dest='build_type',
                             choices=['daily', 'tinderbox', 'try'],
                             default='daily',
                             help='Type of the build (daily, tinderbox, try).'
                             ' Default: %default')
    build_options.add_option('--build-version',
                             dest='build_version',
                             help='The version of the build to test')
    parser.add_option_group(build_options)

    update_options = optparse.OptionGroup(parser, "Update test specific options")
    update_options.add_option('--update-channel',
                              dest='update_channel',
                              help='The update channel to use for the update test')
    update_options.add_option('--update-target-build-id',
                              dest='update_target_build_id',
                              help='The expected BUILDID of the updated build')
    update_options.add_option('--update-target-version',
                              dest='update_target_version',
                              help='The expected version of the updated build')
    parser.add_option_group(update_options)

    (options, args) = parser.parse_args()

    try:
        path = os.path.abspath(os.path.join(here, 'venv'))
        runner = Runner(venv_path=path)
        runner.run_tests(options, args)
    except subprocess.CalledProcessError as e:
        sys.exit(e)

if __name__ == '__main__':
    main()
