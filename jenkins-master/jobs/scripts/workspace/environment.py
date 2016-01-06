#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import logging
import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger('mozmill-ci')


def activate(venv_path):
    """Activate the virtual environment at the specified path."""
    script_dir = 'Scripts' if sys.platform == 'win32' else 'bin'
    env_activate_file = os.path.join(venv_path, script_dir, 'activate_this.py')

    logger.info('Activate environment: {}'.format(env_activate_file))
    execfile(env_activate_file, dict(__file__=env_activate_file))


def create(venv_path, requirements=None):
    """Create a new virtual environment.

    Optionally install additional packages as specified by the requirements file.

    """
    command = ['virtualenv', venv_path]
    logger.info('Create virtual environment: {}'.format(command))
    subprocess.check_call(command)

    if requirements:
        activate(venv_path)

        # Using --no-deps to help make unpinned sub-dependencies more obvious.
        command = ['pip', 'install', '--no-deps', '-r', requirements]
        logger.info('Install additional requirements: {}'.format(command))
        subprocess.check_call(command)


def exists(venv_path):
    """Checks if the specified virtual environment exists."""
    return os.path.isdir(venv_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--create',
                        action='store_true',
                        help='If set a new environment will be created.')
    parser.add_argument('venv_path',
                        help='Path to the virtual environment.')
    parser.add_argument('--requirements',
                        help='File with a list of required modules to be installed.')
    args = parser.parse_args()

    if args.create:
        create(args.venv_path, requirements=args.requirements)
    else:
        if os.path.isdir(args.venv_path):
            logger.info('Environment has been found at: %s' % args.venv_path)
        else:
            logger.info('Environment has not been found. Run with --create to create it.')
