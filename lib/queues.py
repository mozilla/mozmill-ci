# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import logging
import re

from kombu import Exchange, Queue
import requests
import taskcluster


class PulseQueue(Queue):

    def __init__(self, name=None, exchange_name=None, exchange=None,
                 durable=False, auto_delete=True, callback=None,
                 pulse_config=None, **kwargs):
        self.callback = callback
        self.pulse_config = pulse_config or {}

        self.data = None
        self.logger = logging.getLogger('mozmill-ci')

        durable = durable or self.pulse_config.get('durable', False)

        if exchange_name:
            # Using passive mode is important, otherwise pulse returns 403
            exchange = Exchange(exchange_name, type='topic', passive=True)

        Queue.__init__(self, name=name, exchange=exchange, durable=durable,
                       auto_delete=not durable, **kwargs)

    def _preprocess_message(self, body, message):
        raise NotImplementedError('Method has to be implemented in subclass.')

    def is_valid_locale(self, tree, locale):
        whitelist = self.pulse_config['trees'][tree]['locales']
        blacklist = self.pulse_config['trees'][tree]['blacklist']['locales']

        return locale not in blacklist and (not whitelist or locale in whitelist)

    def is_valid_platform(self, tree, platform):
        platforms = self.pulse_config['trees'][tree]['platforms']

        return not platforms or platform in platforms

    def is_valid_product(self, tree, product):
        products = self.pulse_config['trees'][tree]['products']

        return not products or product in products

    def is_valid_tree(self, tree):
        trees = self.pulse_config['trees'].keys()

        return not trees or tree in trees

    def has_valid_tags(self, tree, tags):
        all_tags = set(self.pulse_config['trees'][tree]['tags'])

        return not all_tags or all_tags.issubset(set(tags))

    def _on_message(self, data):
        raise NotImplementedError('Method has to be implemented in subclass.')

    def process_message(self, body, message):
        """Top level callback processing pulse messages.

        The callback tries to handle and log all exceptions
        :param body: kombu.Message.body
        :param message: kombu.Message
        """
        try:
            self.logger.debug('Received message for routing key "{}": {}'.format(self.routing_key,
                                                                                 json.dumps(body)))
            preprocessed_body = self._preprocess_message(body, message)
            self._on_message(preprocessed_body)

        except ValueError as e:
            self.logger.debug(e.message)

        except Exception:
            self.logger.exception('Failed to process Mozilla Pulse message.')

        finally:
            if message:
                message.ack()


class NormalizedBuildQueue(PulseQueue):

    def __init__(self, exchange_name='exchange/build/normalized',
                 routing_key='build.#', **kwargs):

        PulseQueue.__init__(self, exchange_name=exchange_name,
                            routing_key=routing_key, **kwargs)

    def _on_message(self, data):
        # Check if its a valid tree
        tree = data['tree']
        if not self.is_valid_tree(tree):
            raise ValueError('Cancel build request due to invalid tree: {}'.
                             format(tree))

        # Check if it's a valid product
        if not self.is_valid_product(tree, data['product'].lower()):
            raise ValueError('Cancel build request due to invalid product: {}'.
                             format(data['product'].lower()))

        # Check if it's a valid platform
        if not self.is_valid_platform(tree, data['platform']):
            raise ValueError('Cancel build request due to invalid platform: {}'.
                             format(data['platform']))

        # Check if there are valid tags
        if not self.has_valid_tags(tree, data['tags']):
            raise ValueError('Cancel build request due to invalid tags: {}'.
                             format(data['tags']))

        # Check if it's a valid locale
        if not self.is_valid_locale(tree, data['locale']):
            raise ValueError('Cancel build request due to invalid locale: {}'.
                             format(data['locale']))

        # Candidate builds of betas and releases are shipped by Releng with a branch named
        # release-mozilla-(release|beta|esrXX). We have to strip the leading 'release-'
        # portion to get the real branch which we need for our firefox-ui-tests branch checkout.
        data['branch'] = tree.replace('release-', '')

        build_properties = {
            'allowed_testruns': ['functional'],
            'branch': data['branch'],
            'buildid': data['buildid'],
            'build_number': data.get('build_number'),
            'build_url': data.get('buildurl'),  # not present in l10n builds
            'locale': data['locale'],
            'platform': data['platform'],
            'product': data['product'].lower(),
            'revision': data['revision'],
            'status': data['status'],
            'tags': data['tags'],
            'tree': data['tree'],
            'version': data['version'],
            'raw_json': data,
        }
        self.callback(**build_properties)

    def _preprocess_message(self, body, message):
        # We are not interested in the meta data
        return body.get('payload', body)


class FunsizeTaskCompletedQueue(PulseQueue):
    # Routing keys we are interested in for pre-processing the funsize notification
    # are of form: index.funsize.v1.mozilla-central.latest.win32.4.5.balrog
    cc_key_regex = re.compile(r'.*funsize.*\.v1\.(?P<tree>.*)\.latest\.'
                              '(?P<platform>.*?)\..*\.balrog')

    def __init__(self, exchange_name='exchange/taskcluster-queue/v1/task-completed',
                 routing_key='#.funsize-balrog.#', **kwargs):
        PulseQueue.__init__(self, exchange_name=exchange_name,
                            routing_key=routing_key, **kwargs)

    def _on_message(self, data):
        # In case of --push-update-message we only have a single locale contained
        if isinstance(data, dict):
            data = [data]

        for update in data:
            try:
                # Check if its a valid tree
                tree = update['branch']
                if not self.is_valid_tree(tree):
                    raise ValueError('Cancel update request due to invalid tree: {}'.
                                     format(tree))

                # Check if it's a valid product
                if not self.is_valid_product(tree, update['appName'].lower()):
                    raise ValueError('Cancel update request due to invalid product: {}'.
                                     format(update['appName'].lower()))

                # Check if it's a valid platform
                if not self.is_valid_platform(tree, update['platform']):
                    raise ValueError('Cancel update request due to invalid platform: {}'.
                                     format(update['platform']))

                # Check if it's a valid locale
                if not self.is_valid_locale(tree, update['locale']):
                    raise ValueError('Cancel update request due to invalid locale: {}'.
                                     format(update['locale']))

                update_properties = {
                    'allowed_testruns': ['update'],
                    'branch': update['branch'],
                    'buildid': update['from_buildid'],
                    'locale': update['locale'],
                    'platform': update['platform'],
                    'product': update['appName'].lower(),
                    'revision': update['revision'],
                    'target_buildid': update['to_buildid'],
                    'target_version': update['version'],
                    'tree': update['branch'],
                    'update_number': update['update_number'],
                    'raw_json': update,
                }
                self.callback(**update_properties)

            except ValueError as e:
                self.logger.info(e.message)
            except Exception:
                self.logger.exception('Failed to process update message.')

    def _preprocess_message(self, body, message=None):
        """Download the update manifest by processing the received funsize message."""
        # If a message is present, check if the routing keys contain updates we want to test.
        # If not, do an early abort to prevent an unnecessary query of taskcluster and download
        # of the funsize update manifest from S3.
        if message:
            for routing_key in message.headers['CC']:
                try:
                    match = self.cc_key_regex.search(routing_key)
                    if not match:
                        continue

                    self.logger.debug('Found routing key: {}'.format(match.group(0)))
                    tree = match.group('tree')

                    # If we don't cover the current tree no action is needed even for other
                    # entries in that message because all have the same tree
                    if not self.is_valid_tree(tree):
                        raise ValueError('Cancel update request due to invalid tree: {}'.
                                         format(tree))

                    # If we don't cover the current platform no action is needed even for other
                    # entries in that message because all have the same platform
                    if not self.is_valid_platform(tree, match.group('platform')):
                        raise ValueError('Cancel update request due to invalid platform: {}'.
                                         format(match.group('platform')))

                except ValueError:
                    raise

                except:
                    # Just log but don't care about any failure
                    self.logger.exception('Failed to preprocess the message.')

        # In case of --push-update-message we already have the wanted manifest
        if 'workerId' not in body:
            return body

        # Download the manifest from S3 for full processing
        manifest = None
        queue = taskcluster.client.Queue()
        url = queue.buildUrl('getLatestArtifact', body['status']['taskId'],
                             'public/env/manifest.json')
        response = requests.get(url)
        try:
            response.raise_for_status()

            manifest = response.json()
            self.logger.debug('Received update manifest: {}'.format(manifest))
        finally:
            response.close()

        return manifest
