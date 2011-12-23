import json
import os
import sys

import jenkins
from mozillapulse import consumers


PRODUCT = "firefox"
BRANCHES = ['mozilla-central', 'mozilla-aurora']
PLATFORMS = ['linux', 'linux64', 'macosx64', 'win32', 'win64']
LOCALES = ['en-US']

PLATFORM_MAP = {'linux': 'linux',
                'linux64': 'linux64',
                'macosx': 'mac',
                'macosx64': 'mac',
                'win32': 'win32',
                'win64': 'win64'}


#EXTRA_PLATFORMS = ['linux-debug', 'linux64-debug',
#                   'macosx-debug', 'macosx64-debug',
#                   'win32-debug']



j = jenkins.Jenkins('http://localhost:8080') #, 'qa-auto', 'mozqa')


def handle_notification(data, message):
    routing_key = data['_meta']['routing_key']

    # If it's not a notificaton for finished build processes we are not interested in
    if not routing_key.endswith(".finished") or "test" in routing_key:
        return

    # Only the builders for l10n repacks offer the build id of the previous build
    # which we want to use for our update tests
    if not 'l10n' in routing_key:
        return

    # Create dictionary with properties of the build
    if data.get('payload') and data['payload'].get('build'):
        props = dict((k, v) for (k, v, source) in data['payload']['build'].get('properties'))
    else:
        props = dict()

    # If the product doesn't match the expected one we are not interested
    if not props.get('product') == PRODUCT:
        return

    # If the branch is not allowed we are not interested
    if not props.get('branch') in BRANCHES:
        return

    # If the platform is not allowed we are not interested
    if not props.get('platform') in PLATFORMS:
        return

    # Only regular daily builds will provide a previous build id
    if not props.get('previous_buildid'):
        return

    # Test for installer
    url = props.get('packageUrl')
    if props.has_key('installerFilename'):
        url = '/'.join([os.path.dirname(url), props.get('installerFilename')])

    print "Routing Key: %s - Branch: %s" % (routing_key, props.get('branch'))
    print "%(PRODUCT)s %(VERSION)s %(PLATFORM)s %(LOCALE)s %(BUILDID)s %(PREV_BUILDID)s" % {
              'PRODUCT': props.get('product'),
              'VERSION': props.get('appVersion'),
              'PLATFORM': props.get('stage_platform'),
              'LOCALE': props.get('locale', 'en-US'),
              'BUILDID': props.get('buildid'),
              'PREV_BUILDID': props.get('previous_buildid'),
              }
    print "Download: %s" % url
    print "Props: %s\n\n" % json.dumps(props)

    if not 'mac' in props['platform']:
        return

    j.build_job('functional', {'BRANCH': props['branch'],
                               'PLATFORM': PLATFORM_MAP[props['platform']],
                               'LOCALE': props.get('locale', 'en-US'),
                               'BUILD_ID': props['buildid'],})

pulse = consumers.BuildConsumer(applabel='qa-auto@mozilla.com|daily_testrun')
pulse.configure(topic='#', callback=handle_notification)

while True:
    try:
        pulse.listen()
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception, e:
        print str(e)
