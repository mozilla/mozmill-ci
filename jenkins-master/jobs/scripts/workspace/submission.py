#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import os
import re
import socket
import time
from urlparse import urljoin, urlparse
import uuid

from config import config
from jenkins import JenkinsDefaultValueAction


here = os.path.dirname(os.path.abspath(__file__))

RESULTSET_FRAGMENT = 'api/project/{repository}/resultset/?revision={revision}'
JOB_FRAGMENT = '/#/jobs?repo={repository}&revision={revision}'

BUILD_STATES = ['running', 'completed']


class FirefoxUIResultParser(object):

    BUSTED = 'busted'
    SUCCESS = 'success'
    TESTFAILED = 'testfailed'
    UNKNOWN = 'unknown'

    def __init__(self, retval, log_file):
        self.retval = retval
        self.log_file = log_file
        self.failure_re = re.compile(r'(^TEST-UNEXPECTED-FAIL|TEST-UNEXPECTED-ERROR)|'
                                     r'(.*CRASH: )|'
                                     r'(Crash reason: )')
        self.failures = []
        self.parse()

    def parse(self):
        try:
            with open(self.log_file, 'r') as f:
                for line in f.readlines():
                    if self.failure_re.match(line):
                        self.failures.append(line)
        except IOError:
            print('Cannot parse failures due to missing log file: {}'.format(self.log_file))

    @property
    def status(self):
        status = self.UNKNOWN

        # retval.txt was not written - so most likely an abort
        if self.retval is None or (self.retval and not self.failures):
            status = self.BUSTED

        elif not self.failures:
            status = self.SUCCESS

        elif self.failures:
            status = self.TESTFAILED

        return status

    def failures_as_json(self):
        failures = {'all_errors': [], 'errors_truncated': True}

        for failure in self.failures:
            failures['all_errors'].append({'line': failure, 'linenumber': 1})

        return failures


class Submission(object):

    def __init__(self, repository, revision, settings,
                 treeherder_url=None, treeherder_client_id=None, treeherder_secret=None):
        self.repository = repository
        self.revision = revision
        self.settings = settings

        self._job_details = []

        self.url = treeherder_url
        self.client_id = treeherder_client_id
        self.secret = treeherder_secret

        if not self.client_id or not self.secret:
            raise ValueError('The client_id and secret for Treeherder must be set.')

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

    def create_job(self, guid, **kwargs):
        job = TreeherderJob()

        job.add_job_guid(guid)
        job.add_tier(self.settings['treeherder']['tier'])

        job.add_product_name('firefox')

        job.add_project(self.repository)
        job.add_revision_hash(self.retrieve_revision_hash())

        # Add platform and build information
        job.add_machine(socket.getfqdn())
        platform = self._get_treeherder_platform()
        job.add_machine_info(*platform)
        job.add_build_info(*platform)

        # TODO debug or others?
        job.add_option_collection({'opt': True})

        # TODO: Add e10s group once we run those tests
        job.add_group_name(self.settings['treeherder']['group_name'].format(**kwargs))
        job.add_group_symbol(self.settings['treeherder']['group_symbol'].format(**kwargs))

        # Bug 1174973 - for now we need unique job names even in different groups
        job.add_job_name(self.settings['treeherder']['job_name'].format(**kwargs))
        job.add_job_symbol(self.settings['treeherder']['job_symbol'].format(**kwargs))

        job.add_start_timestamp(int(time.time()))

        # Bug 1175559 - Workaround for HTTP Error
        job.add_end_timestamp(0)

        return job

    def retrieve_revision_hash(self):
        if not self.url:
            raise ValueError('URL for Treeherder is missing.')

        lookup_url = urljoin(self.url,
                             RESULTSET_FRAGMENT.format(repository=self.repository,
                                                       revision=self.revision))

        # self.logger.debug('Getting revision hash from: %s' % lookup_url)
        print('Getting revision hash from: {}'.format(lookup_url))
        response = requests.get(lookup_url)
        response.raise_for_status()

        if not response.json():
            raise ValueError('Unable to determine revision hash for {}. '
                             'Perhaps it has not been ingested by '
                             'Treeherder?'.format(self.revision))

        return response.json()['results'][0]['revision_hash']

    def submit(self, job, logs=None):
        logs = logs or []

        job.add_submit_timestamp(int(time.time()))

        # We can only submit job info once, so it has to be done in completed
        if self._job_details:
            job.add_artifact('Job Info', 'json', {'job_details': self._job_details})

        job_collection = TreeherderJobCollection()
        job_collection.add(job)

        print('Sending results to Treeherder: {}'.format(job_collection.to_json()))
        url = urlparse(self.url)
        client = TreeherderClient(protocol=url.scheme, host=url.hostname,
                                  client_id=self.client_id, secret=self.secret)
        client.post_collection(self.repository, job_collection)

        print('Results are available to view at: {}'.format(
            urljoin(self.url,
                    JOB_FRAGMENT.format(repository=self.repository, revision=self.revision))))

    def submit_running_job(self, job):
        job.add_state('running')

        self.submit(job)

    def submit_completed_job(self, job, retval, uploaded_logs):
        """Update the status of a job to completed.
        """
        # Parse TBPL log for failures
        tbpl_log = uploaded_logs.get('tbpl.log', {})

        parser = FirefoxUIResultParser(retval, self.settings['logs']['tbpl.log'])
        job.add_result(parser.status)

        if os.path.isfile(self.settings['logs']['tbpl.log']):
            job.add_log_reference(self.settings['logs']['tbpl.log'],
                                  tbpl_log.get('url'),
                                  parse_status='parsed')
            job.add_artifact(name='text_log_summary', artifact_type='json',
                             blob={'step_data': parser.failures_as_json(),
                                   'logurl': tbpl_log.get('url')})

        # If the Jenkins BUILD_URL environment variable is present add it as artifact
        # TODO: Figure out how to send it already for running state. If I do so right
        # now the logs won't be uploaded.
        if os.environ.get('BUILD_URL'):
            self._job_details.append({
                'title': 'Inspect Jenkins Build (VPN required)',
                'value': os.environ['BUILD_URL'],
                'content_type': 'link',
                'url': os.environ['BUILD_URL']
            })

        # Add all uploaded logs as artifacts
        for log in uploaded_logs:
            self._job_details.append({
                'title': log,
                'value': uploaded_logs[log]['url'],
                'content_type': 'link',
                'url': uploaded_logs[log]['url'],
            })

        job.add_state('completed')
        job.add_end_timestamp(int(time.time()))

        self.submit(job)


def upload_log_files(guid, logs,
                     bucket_name=None, access_key_id=None, access_secret_key=None):
    # If AWS credentials are given we want to upload the log files and attach
    # as artifacts to the treeherder job results
    if not bucket_name:
        print('No AWS Bucket name specified - skipping upload of artifacts.')
        return {}

    s3_bucket = S3Bucket(bucket_name, access_key_id=access_key_id,
                         access_secret_key=access_secret_key)

    uploaded_logs = {}

    for log in logs:
        try:
            if os.path.isfile(logs[log]):
                remote_path = '{dir}/{filename}'.format(dir=str(guid),
                                                        filename=os.path.basename(log))
                url = s3_bucket.upload(logs[log], remote_path)

                uploaded_logs.update({log: {'path': logs[log], 'url': url}})
                print('Uploaded {path} to {url}'.format(path=logs[log], url=url))

        except Exception as e:
            print('Failure uploading "{path}" to S3: {ex}'.format(path=logs[log],
                                                                  ex=str(e)))

    return uploaded_logs


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--locale',
                        action=JenkinsDefaultValueAction,
                        default='en-US',
                        help='The locale of the build. Default: %(default)s.')
    parser.add_argument('--test-type',
                        choices=config['test_types'].keys(),
                        required=True,
                        help='The type of test for building the job name and symbol.')
    parser.add_argument('--repository',
                        required=True,
                        help='The repository name the build was created from.')
    parser.add_argument('--revision',
                        required=True,
                        help='The revision of the build.')
    parser.add_argument('--build-state',
                        choices=BUILD_STATES,
                        required=True,
                        help='The state of the build')
    parser.add_argument('venv_path',
                        help='Path to the virtual environment to use.')

    aws_group = parser.add_argument_group('AWS', 'Arguments for Amazon S3')
    aws_group.add_argument('--aws-bucket',
                           default=os.environ.get('AWS_BUCKET'),
                           help='The S3 bucket name.')
    aws_group.add_argument('--aws-key',
                           default=os.environ.get('AWS_ACCESS_KEY_ID'),
                           help='Access key for Amazon S3.')
    aws_group.add_argument('--aws-secret',
                           default=os.environ.get('AWS_SECRET_ACCESS_KEY'),
                           help='Access secret for Amazon S3.')

    treeherder_group = parser.add_argument_group('treeherder', 'Arguments for Treeherder')
    treeherder_group.add_argument('--treeherder-url',
                                  default=os.environ.get('TREEHERDER_URL'),
                                  help='URL to the Treeherder server.')
    treeherder_group.add_argument('--treeherder-client-id',
                                  default=os.environ.get('TREEHERDER_CLIENT_ID'),
                                  help='Client ID for submission to Treeherder.')
    treeherder_group.add_argument('--treeherder-secret',
                                  default=os.environ.get('TREEHERDER_SECRET'),
                                  help='Secret for submission to Treeherder.')

    update_group = parser.add_argument_group('update', 'Arguments for update tests')
    update_group.add_argument('--update-number',
                              action=JenkinsDefaultValueAction,
                              help='The number of the partial update: today - N days')

    return vars(parser.parse_args())


if __name__ == '__main__':
    kwargs = parse_args()

    # Activate the environment, and create if necessary
    import environment
    if environment.exists(kwargs['venv_path']):
        environment.activate(kwargs['venv_path'])
    else:
        environment.create(kwargs['venv_path'], os.path.join(here, 'requirements.txt'))

    # Can only be imported after the environment has been activated
    import mozinfo
    import requests

    from s3 import S3Bucket
    from thclient import TreeherderClient, TreeherderJob, TreeherderJobCollection

    settings = config['test_types'][kwargs['test_type']]
    th = Submission(kwargs['repository'], kwargs['revision'][:12],
                    treeherder_url=kwargs['treeherder_url'],
                    treeherder_client_id=kwargs['treeherder_client_id'],
                    treeherder_secret=kwargs['treeherder_secret'],
                    settings=settings)

    # State 'running'
    if kwargs['build_state'] == BUILD_STATES[0]:
        job_guid = str(uuid.uuid4())
        job = th.create_job(job_guid, **kwargs)
        th.submit_running_job(job)
        with file('job_guid.txt', 'w') as f:
            f.write(job_guid)

    # State 'completed'
    elif kwargs['build_state'] == BUILD_STATES[1]:
        # Read in job guid to update the report
        try:
            with file('job_guid.txt', 'r') as f:
                job_guid = f.read()
        except:
            job_guid = str(uuid.uuid4())

        # Read return value of the test script
        try:
            with file('retval.txt', 'r') as f:
                retval = int(f.read())
        except IOError:
            retval = None

        job = th.create_job(job_guid, **kwargs)
        uploaded_logs = upload_log_files(job_guid, settings['logs'],
                                         bucket_name=kwargs.get('aws_bucket'),
                                         access_key_id=kwargs.get('aws_key'),
                                         access_secret_key=kwargs.get('aws_secret'),)
        th.submit_completed_job(job, retval, uploaded_logs=uploaded_logs)
