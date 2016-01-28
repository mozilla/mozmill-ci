#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import optparse
import os
import sys
import time


ACTIVATE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'jenkins-env', 'bin', 'activate_this.py')


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

    # Configure logging levels for sub modules. Set to ERROR by default.
    sub_log_level = logging.ERROR
    if options.log_level == logging.getLevelName(logging.DEBUG):
        sub_log_level = logging.DEBUG
    logging.getLogger('mozdownload').setLevel(sub_log_level)
    logging.getLogger('redo').setLevel(sub_log_level)
    logging.getLogger('requests').setLevel(sub_log_level)
    logging.getLogger('thclient').setLevel(sub_log_level)

    # Auto import the virtual environment so the script can directly
    # be called without having to source into first.
    try:
        execfile(ACTIVATE_SCRIPT, dict(__file__=ACTIVATE_SCRIPT))
        logger.info('Virtual environment activated successfully.')
    except IOError:
        logger.exception('Could not activate virtual environment at "{}"'.format(ACTIVATE_SCRIPT))
        sys.exit(1)

    from lib.automation import FirefoxAutomation

    FirefoxAutomation(configfile=args[0],
                      pulse_authfile=options.pulse_authfile,
                      debug=options.debug,
                      log_folder=options.log_folder,
                      logger=logger,
                      message=options.message,
                      display_only=options.display_only)


if __name__ == "__main__":
    main()
