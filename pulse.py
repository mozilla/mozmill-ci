from datetime import datetime
import json
import optparse
import os
import re
import sys

import jenkins
from mozillapulse import consumers


# Configuration settings which have to be moved out of the script
config = {
    'jenkins': {
        'url': 'http://localhost:8080',
        'username': 'mozilla',
        'password': 'test1234',
    },
    'pulse': {
        'routing_key_regex': r'build\..+-l10n-nightly\.\d+\.finished',
        'branches': ['mozilla-central', 'mozilla-aurora'],
        'locales': ['de', 'en-US', 'fr', 'it', 'ja', 'es-ES', 'pl', 'pt-BR', 'ru', 'tr'],
        'platforms': ['macosx', 'macosx64'],
        'products': ['firefox'],
    }
}


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
debug = False
log_folder = None


def handle_notification(data, message):
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

    # If the product doesn't match the expected one we are not interested
    if not product in config['pulse']['products']:
        return

    # Output debug information if requested
    if debug:
        print "%s - Routing Key: %s - Branch: %s" % (str(datetime.now()),
                                                     routing_key,
                                                     branch)

        try:
            folder = os.path.join(log_folder, branch)
            if not os.path.exists(folder):
                os.makedirs(folder)
            f = open(os.path.join(folder, routing_key), 'w')
            f.write(json.dumps(data))
        finally:
            f.close()

    # If the branch is not allowed we are not interested
    if not branch in config['pulse']['branches'] or \
       not platform in config['pulse']['platforms'] or \
       not locale in config['pulse']['locales']:
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
                                    'TARGET_BUILD_ID': buildid })

    # Functional Test
    j.build_job('functional-test', {'BRANCH': branch,
                                    'PLATFORM': PLATFORM_MAP[platform],
                                    'LOCALE': locale,
                                    'BUILD_ID': props.get('buildid')})


def main():
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

    debug = options.debug
    log_folder = options.log_folder

    # Initialize Pulse connection
    pulse = consumers.BuildConsumer(applabel='qa-auto@mozilla.com|daily_testrun')
    pulse.configure(topic='#', callback=handle_notification)

    if options.message:
        try:
            f = open(options.message, 'r')
            data = json.loads(f.read())
            handle_notification(data, None)
        finally:
            f.close()
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
