"""Script to create and trigger Firefox testruns in Jenkins."""

import ConfigParser
import copy
import logging
import os
import re
import sys
import time

import jenkins
import requests

from mozdownload import FactoryScraper
from mozdownload import errors as download_errors
from thclient import TreeherderClient


logging.basicConfig(format='%(levelname)s | %(message)s', level=logging.DEBUG)
logger = logging.getLogger(__name__)


def query_file_url(properties, property_overrides=None):
    """Query for the specified build by using mozdownload.

    This method uses the properties as received via Mozilla Pulse to query
    the build via mozdownload. Use the property overrides to customize the
    query, e.g. different build or test package files.
    """
    property_overrides = property_overrides or {}

    kwargs = {
        # General arguments for all types of builds
        'build_type': properties.get('build_type'),
        'locale': properties.get('locale'),
        'platform': properties.get('platform'),
        'retry_attempts': 5,
        'retry_delay': 30,

        # Arguments for daily builds
        'branch': properties.get('branch'),
        'build_id': properties.get('buildid'),

        # Arguments for candidate builds
        'build_number': properties.get('build_number'),
        'version': properties.get('version'),

        'logger': logger,
    }

    # Update arguments with given overrides
    kwargs.update(property_overrides)

    logger.debug('Query file details for: %s' % kwargs)
    return FactoryScraper(kwargs['build_type'], **kwargs).url


def get_installer_url(properties):
    """Get the installer URL via mozdownload."""
    return query_file_url(properties)


def get_test_packages_url(properties):
    """Return the URL of the test packages JSON file.

    In case of localized daily builds we can query the en-US build to get
    the URL, but for candidate builds we need the tinderbox build
    of the first parent changeset which was not checked-in by the release
    automation process (necessary until bug 1242035 is not fixed).
    """
    overrides = {
        'locale': 'en-US',
        'extension': 'test_packages.json',
        'build_type': 'tinderbox',
    }

    platform_map = {
        'linux': {'build_platform': 'linux32'},
        'linux64': {'build_platform': 'linux64'},
        'mac': {'build_os': 'mac', 'build_architecture': 'x86_64'},
        'win32': {'build_os': 'win', 'build_architecture': 'x86'},
        'win64': {'build_os': 'win', 'build_architecture': 'x86_64'},
    }

    revision = properties['revision']

    client = TreeherderClient()
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

    overrides['revision'] = revision

    # For update tests we need the test package of the target build. That allows
    # us to add fallback code in case major parts of the ui are changing in Firefox.
    if properties.get('target_buildid'):
        overrides['build_id'] = properties['target_buildid']

    # The test package json file has a prefix with bug 1239808 fixed. Older builds need
    # a fallback to a prefix-less filename.
    try:
        url = query_file_url(properties, property_overrides=overrides)
    except download_errors.NotFoundError:
        extension = overrides.pop('extension')
        build_url = query_file_url(properties, property_overrides=overrides)
        url = '{}/{}'.format(build_url[:build_url.rfind('/')], extension)
        r = requests.head(url)
        if r.status_code != 200:
            url = None

    return url


def get_build_details(version_string):
    """Extract the type, version, and build_number of a version as given in the config file."""
    # Expression to parse versions like: '5.0', '5.0#3', '5.0b1',
    # '5.0b2#1', '10.0esr#1', '10.0.4esr#1'
    pattern = re.compile(r'(?P<version>\d+[^#\s]+)(#(?P<build>\d+))?')
    version, build_number = pattern.match(version_string).group('version', 'build')

    if 'esr' in version:
        branch = 'mozilla-esr{}'.format(version.split('.')[0])
    elif 'b' in version:
        branch = 'mozilla-beta'
    else:
        branch = 'mozilla-release'

    return {
        'branch': branch,
        'build_number': build_number,
        'build_type': 'candidate' if build_number else 'release',
        'version': version,
    }


def get_target_build_details(properties, platform):
    """Retrieve build details for the target version."""
    props = copy.deepcopy(properties)
    props.update({'platform': platform})

    # Retrieve platform specific info.txt
    overrides = {
        'locale': 'en-US',
        'extension': 'json',
    }
    logger.info('Retrieving target build details for Firefox {} build {} on {}...'.format(
        props['version'], props['build_number'], props['platform']))
    url = query_file_url(props, property_overrides=overrides)
    r = requests.get(url)

    # Update revision to retrieve the test package URL
    props.update({'revision': r.json()['moz_source_stamp']})

    details = {
        'build_id': r.json()['buildid'],
        'revision': props['revision'],
        'test_packages_url': get_test_packages_url(props)
    }

    logger.info('Target build details: {}'.format(details))

    return details


def load_authentication_config():
    root_dir = os.path.abspath(__file__)
    for p in range(0, 5):
        root_dir = os.path.dirname(root_dir)
    authfile = os.path.join(root_dir, '.authentication.ini')

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

    return auth


def main():
    auth = load_authentication_config()
    logger.info('Connecting to Jenkins at "%s"...' % auth['jenkins']['url'])
    j = jenkins.Jenkins(auth['jenkins']['url'],
                        username=auth['jenkins']['user'],
                        password=auth['jenkins']['password'])
    logger.info('Connected to Jenkins.')

    if not len(sys.argv) == 2:
        logger.error('Configuration file not specified.')
        logger.error('Usage: %s config' % sys.argv[0])
        sys.exit(1)

    # Read-in configuration options
    config = ConfigParser.SafeConfigParser()
    config.read(sys.argv[1])

    # Read all testrun entries
    testrun = {}
    for entry in config.options('testrun'):
        testrun.update({entry: config.get('testrun', entry, raw=True)})

    # Retrieve version details of the target build
    testrun.update(get_build_details(testrun.pop('target-version')))
    if testrun['build_type'] != 'candidate':
        raise Exception('Target build has to be a candidate build.')

    # Cache for platform specific target build details
    target_build_details = {}

    # Iterate through all target nodes
    job_count = 0
    for section in config.sections():
        # Retrieve the platform, i.e. win32 or linux64
        if not config.has_option(section, 'platform'):
            continue

        node_labels = section.split()
        platform = config.get(section, 'platform')

        if platform not in target_build_details:
            target_build_details[platform] = get_target_build_details(testrun, platform)

        # Iterate through all builds per platform
        for entry in config.options(section):
            try:
                # Skip all non version lines
                build_details = get_build_details(entry)
                build_details.update({'platform': platform})
            except:
                continue

            for locale in config.get(section, entry).split():
                build_details.update({'locale': locale})

                parameters = {
                    'BRANCH': testrun['branch'],
                    'INSTALLER_URL': get_installer_url(build_details),
                    'LOCALE': locale,
                    'NODES': ' && '.join(node_labels),
                    'REVISION': target_build_details[platform]['revision'],
                    'TEST_PACKAGES_URL': target_build_details[platform]['test_packages_url'],
                }

                if testrun['script'] == 'update':
                    parameters['TARGET_BUILD_ID'] = target_build_details[platform]['build_id']
                    parameters['CHANNEL'] = testrun['channel']
                    parameters['ALLOW_MAR_CHANNEL'] = \
                        testrun.get('allow-mar-channel', None)
                    parameters['UPDATE_NUMBER'] = build_details['version']

                logger.info('Triggering job: ondemand_%s with %s' % (testrun['script'],
                                                                     parameters))
                j.build_job('ondemand_%s' % testrun['script'], parameters)
                job_count += 1

            # Give Jenkins a bit of breath to process other threads
            time.sleep(2.5)

    logger.info('%d jobs have been triggered.' % job_count)

if __name__ == "__main__":
    main()
