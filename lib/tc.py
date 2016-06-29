# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


import copy
import datetime
import logging
import os

import jinja2
import taskcluster
import yaml

import lib.errors as errors


logger = logging.getLogger('mozmill-ci')

URI_TASK_INSPECTOR = 'https://tools.taskcluster.net/task-inspector/#'


class FirefoxUIWorker(object):

    def __init__(self, client_id, authentication):
        self.client_id = client_id
        self.authentication = authentication

    def createTestTask(self, flavor, payload):
        """Create task in Taskcluster for given type of test flavor.

        :param flavor: Type of test to run (functional or update).
        :param payload: Properties of the build and necessary resources.
        """
        queue = taskcluster.Queue({'credentials': {'clientId': self.client_id,
                                                   'accessToken': self.authentication}})
        slugid = taskcluster.stableSlugId()('fx-ui-{}'.format(flavor))

        return queue.createTask(slugid, payload)


    def generate_task_payload(self, flavor, properties):
        """Generate the task payload data for the given type of test and properties.

        :param flavor: Type of test to run (functional or update).
        :param properties: Task properties for template rendering
        """
        template_file = os.path.join(os.path.dirname(__file__),
                                     'tasks', '{}.yml'.format(flavor))
        if not os.path.isfile(template_file):
            raise errors.NotSupportedException('Test type "{}" not supported.'.format(flavor))

        with open(template_file) as f:
            template = jinja2.Template(f.read(), undefined=jinja2.StrictUndefined)

        template_vars = copy.deepcopy(properties)
        template_vars.update({
            'stableSlugId': taskcluster.stableSlugId(),
            'now': taskcluster.stringDate(datetime.datetime.utcnow()),
            'fromNow': taskcluster.fromNow,
            'docker_task_id': self.get_docker_task_id(properties),
        })

        rendered = template.render(**template_vars)

        return yaml.safe_load(rendered)

    def get_docker_task_id(self, properties):
        """Retrieve docker image task Id used by tests on TC.

        To get the task id of the 'desktop-test' docker image as used by desktop tests
        for a given build the Index has to be queried first. When the task for the build
        has been found, check all its dependent tasks for the first appearance of the
        'desktop-test' worker type. Within its payload the task id of the docker task
        can be extracted.

        Bug 1276352 - Not all Taskcluster builds are Tier-1 yet. So the index also
        contains BuildBot entries. To ensure we get a TC build force to Linux64 dbg.

        :param properties: Properties of the build and necessary resources.
        """
        build_index = 'gecko.v2.{branch}.revision.{rev}.firefox.{platform}-dbg'.format(
            branch=properties['branch'],
            rev=properties['revision'],
            platform=properties['platform'],
        )

        try:
            logger.debug('Querying Taskcluster for "desktop-test" docker image for "{}"...'.format(
                properties['branch']))
            build_task_id = taskcluster.Index().findTask(build_index)['taskId']
        except taskcluster.exceptions.TaskclusterFailure:
            raise errors.NotFoundException('Required build not found for TC index', build_index)

        task_id = None
        continuation_token = None
        while not task_id:
            options = {'limit': 5}
            if continuation_token:
                options.update({'continuationToken': continuation_token})

            resp = taskcluster.Queue().listDependentTasks(build_task_id,
                                                          options=options)
            for task in resp['tasks']:
                if task['task'].get('extra', {}).get('suite', {}).get('name') == 'firefox-ui':
                    task_id = task['status']['taskId']
                    break

            continuation_token = resp.get('continuationToken')

            if not continuation_token:
                raise errors.NotFoundException('No tests found which use docker image', image_name)

        task_definition = taskcluster.Queue().task(task_id)

        return task_definition['payload']['image']['taskId']
