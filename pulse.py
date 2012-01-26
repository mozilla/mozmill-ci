#!/usr/bin/env python

# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is MozMill automation code.
#
# The Initial Developer of the Original Code is the Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2011
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Henrik Skupin <mail@hskupin.info>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

from datetime import datetime
import json
import optparse
import os
import re
import socket
import sys

import jenkins
from mozillapulse import consumers


# Map to translate platform ids from Pulse to Mozmill / Firefox
PLATFORM_MAP = {'linux': 'linux',
                'linux-debug': 'linux',
                'linux64': 'linux64',
                'linux64-debug': 'linux64',
                'macosx': 'mac',
                'macosx-debug': 'mac',
                'macosx64': 'mac',
                'macosx64-debug': 'mac',
                'win32': 'win32',
                'win32-debug': 'win32',
                'win64': 'win64',
                'win64-debug': 'win64'}


# Globally shared variables
config = None
debug = False
log_folder = None


class NotFoundException(Exception):
    """Exception for a resource not being found (e.g. no logs)"""
    def __init__(self, message, location):
        self.location = location
        Exception.__init__(self, ': '.join([message, location]))


def handle_notification(data, message):
    # Ensure to acknoledge the message so it gets removed on the server
    message.ack()

    routing_key = data['_meta']['routing_key']

    # Check if the routing key matches the expected regex
    pattern = re.compile(config['pulse']['routing_key_regex'], re.IGNORECASE)
    if not pattern.match(routing_key):
        return

    # Create dictionary with properties of the build
    if data.get('payload') and data['payload'].get('build'):
        props = dict((k, v) for (k, v, source) in data['payload']['build'].get('properties'))
    else:
        props = dict()

    # Retrieve imporant properties
    product = props.get('product')
    branch = props.get('branch')
    buildid = props.get('buildid')
    locale = props.get('locale', 'en-US')
    platform = props.get('platform')
    version = props.get('appVersion')

    # Output logging information for received notification
    print "%s - Routing Key: %s - Branch: %s - Locale: %s" % \
        (str(datetime.now()), routing_key, branch, locale)

    # Save off the notification message if requested
    if debug:
        try:
            folder = os.path.join(log_folder, branch)
            if not os.path.exists(folder):
                os.makedirs(folder)
            f = open(os.path.join(folder, routing_key), 'w')
            f.write(json.dumps(data))
        finally:
            f.close()

    # If one of the expected values do not match we are not interested in the build
    valid_branch = not config['pulse']['branches'] or branch in config['pulse']['branches']
    valid_locale = not config['pulse']['locales'] or locale in config['pulse']['locales']
    valid_platform = not config['pulse']['platforms'] or platform in config['pulse']['platforms']
    valid_product = not config['pulse']['products'] or product in config['pulse']['products']
    
    if not (valid_product and valid_branch and valid_platform and valid_locale):
        return

    # Test for installer
    url = props.get('packageUrl')
    if props.has_key('installerFilename'):
        url = '/'.join([os.path.dirname(url), props.get('installerFilename')])

    print "Trigger tests for %(PRODUCT)s %(VERSION)s %(PLATFORM)s %(LOCALE)s %(BUILDID)s %(PREV_BUILDID)s" % {
              'PRODUCT': product,
              'VERSION': version,
              'PLATFORM': PLATFORM_MAP[platform],
              'LOCALE': locale,
              'BUILDID': buildid,
              'PREV_BUILDID': props.get('previous_buildid'),
              }

    j = jenkins.Jenkins(config['jenkins']['url'],
                        config['jenkins']['username'],
                        config['jenkins']['password'])

    # Update Test: Only execute if a previous build id has been specified
    if props.get('previous_buildid'):
        j.build_job('update-test', {'BRANCH': branch,
                                    'PLATFORM': PLATFORM_MAP[platform],
                                    'LOCALE': locale,
                                    'BUILD_ID': props.get('previous_buildid'),
                                    'TARGET_BUILD_ID': buildid,
                                    'REPORT_URL': config['mozmill']['report_url']})

    # Functional Test
    j.build_job('functional-test', {'BRANCH': branch,
                                    'PLATFORM': PLATFORM_MAP[platform],
                                    'LOCALE': locale,
                                    'BUILD_ID': props.get('buildid'),
                                    'REPORT_URL': config['mozmill']['report_url']})


def read_json_file(filename):
    if not os.path.isfile(filename):
        raise NotFoundException('Specified file cannot be found.', filename)

    try:
        f = open(filename, 'r')
        return json.loads(f.read())
    finally:
        f.close()


def main():
    global config
    global debug
    global log_folder

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
    options, args = parser.parse_args()

    if not len(args):
        parser.error('A configuration file has to be passed in as first argument.')

    config = read_json_file(args[0])
    debug = options.debug
    log_folder = options.log_folder

    # Make the consumer dependent to the host to prevent queue corruption by
    # other machines we are using the same queue name
    applabel = '%s|%s' % (config['pulse']['applabel'], socket.getfqdn())

    # Initialize Pulse connection
    pulse = consumers.BuildConsumer(applabel=applabel,
                                    durable=config['pulse']['durable'])
    pulse.configure(topic='build.*.*.finished', callback=handle_notification)
    print 'Connected to Mozilla Pulse as "%s"...' % applabel

    if options.message:
        data = read_json_file(options.message)
        handle_notification(data, None)
    else:
        while True:
            try:
                pulse.listen()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception, e:
                print str(e)


if __name__ == "__main__":
    main()
