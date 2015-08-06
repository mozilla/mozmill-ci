# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import re
import socket
import time
from urlparse import urljoin, urlparse
import uuid

import mozinfo
import requests
from thclient import TreeherderClient, TreeherderJob, TreeherderJobCollection
from thclient.auth import TreeherderAuth


LOOKUP_FRAGMENT = 'api/project/%s/resultset/?revision=%s'
REVISON_FRAGMENT = '/#/jobs?repo=%s&revision=%s'


class FirefoxUITestJob(TreeherderJob):

    def __init__(self, product_name, locale, group_name, group_symbol):
        TreeherderJob.__init__(self, data={})

        self._details = []

        self.add_job_guid(str(uuid.uuid4()))
        self.add_tier(3)

        self.add_state('running')

        self.add_product_name(product_name)

        # Add platform and build information
        self.add_machine(socket.getfqdn())
        platform = self._get_treeherder_platform()
        self.add_machine_info(*platform)
        self.add_build_info(*platform)

        # TODO debug or others?
        self.add_option_collection({'opt': True})

        # TODO: Add e10s group later
        self.add_group_name(group_name)
        self.add_group_symbol(group_symbol)

        # Bug 1174973 - for now we need unique job names even in different groups
        self.add_job_name("%s (%s)" % (group_name, locale))
        self.add_job_symbol(locale)

        self.add_start_timestamp(int(time.time()))

        # Bug 1175559 - Workaround for HTTP Error
        self.add_end_timestamp(0)

    def _get_treeherder_platform(self):
        platform = None

        info = mozinfo.info

        if info['os'] == 'linux':
            platform = ('linux', '%s%s' % (info['os'], info['bits']), '%s' % info['processor'])

        elif info['os'] == 'mac':
            platform = ('mac', 'osx-%s' % info['os_version'].replace('.', '-'), info['processor'])

        elif info['os'] == 'win':
            versions = {'5.1': 'xp', '6.1': '7', '6.2': '8'}
            bits = ('-%s' % info['bits']) if info['os_version'] != '5.1' else ''
            platform = ('win', 'windows%s%s' % (versions[info['os_version']], '%s' % bits),
                        info['processor'],
                        )

        return platform

    def add_details(self, title, value, content_type, url):
        self._details.append({
            'title': title,
            'value': value,
            'content_type': content_type,
            'url': url, })

    def completed(self, result):
        """Update the status of a job to completed.

        :param result: If completed the result of the job ('success', 'testfailed',
                        'busted', 'exception', 'retry', 'usercancel')
        :param details: Details which will be added as artifacts
        """
        self.add_state('completed')
        self.add_result(result)
        self.add_end_timestamp(int(time.time()))

        if self._details:
            self.add_artifact('Job Info', 'json', {'job_details': self._details})


class JobResultParser(object):

    def __init__(self, log_file):
        self.log_file = log_file
        self.failure_re = re.compile(r'(^TEST-UNEXPECTED-FAIL|TEST-UNEXPECTED-ERROR)|'
                                     r'(.*CRASH: )|'
                                     r'(Crash reason: )')
        self.failures = []
        self.parse()

    def parse(self):
        with open(self.log_file, 'r') as f:
            for line in f.readlines():
                if self.failure_re.match(line):
                    self.failures.append(line)

    @property
    def success(self):
        return self.failures == []

    def failures_as_json(self):
        failures = {'all_errors': [], 'errors_truncated': True}

        for failure in self.failures:
            failures['all_errors'].append({'line': failure, 'linenumber': None})

        return failures


class TreeherderSubmission(object):

    def __init__(self, project, revision, url, key, secret):
        self.project = project
        self.revision = revision
        self.url = url
        self.key = key
        self.secret = secret

    def retrieve_revision_hash(self):
        lookup_url = urljoin(self.url,
                             LOOKUP_FRAGMENT % (self.project, self.revision))

        # self.logger.debug('Getting revision hash from: %s' % lookup_url)
        print('Getting revision hash from: %s' % lookup_url)
        response = requests.get(lookup_url)
        response.raise_for_status()

        assert response.json(), 'Unable to determine revision hash for %s. ' \
                                'Perhaps it has not been ingested by ' \
                                'Treeherder?' % self.revision
        return response.json()['results'][0]['revision_hash']

    def submit_results(self, job):
        job.add_project(self.project)
        job.add_revision_hash(self.retrieve_revision_hash())
        job.add_submit_timestamp(int(time.time()))

        job_collection = TreeherderJobCollection()
        job_collection.add(job)

        # self.logger.info
        print('Sending results to Treeherder: %s' % job_collection.to_json())

        auth = TreeherderAuth(self.key, self.secret, self.project)

        url = urlparse(self.url)
        client = TreeherderClient(protocol=url.scheme, host=url.hostname,
                                  auth=auth)
        client.post_collection(self.project, job_collection)

        # self.logger.info
        print('Results are available to view at: %s' % (
            urljoin(self.url,
                    REVISON_FRAGMENT % (self.project, self.revision))))
