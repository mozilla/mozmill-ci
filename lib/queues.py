# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import logging

from kombu import Exchange, Queue


class PulseQueue(Queue):

    def __init__(self, name=None, exchange_name=None, exchange=None,
                 durable=False, auto_delete=True, callback=None, **kwargs):
        self.callback = callback
        self.logger = logging.getLogger('mozmill-ci')

        if exchange_name:
            # Using passive mode is important, otherwise pulse returns 403
            exchange = Exchange(exchange_name, type='topic', passive=True)

        Queue.__init__(self, name=name, exchange=exchange, durable=durable,
                       auto_delete=not durable, **kwargs)

    def process_message(self, body, message):
        """Top level callback processing pulse messages.

        The callback tries to handle and log all exceptions
        :param body: kombu.Message.body
        :param message: kombu.Message
        """
        try:
            self.callback(body, message)
        except Exception:
            self.logger.exception('Failed to process message')
        finally:
            message.ack()


class NormalizedBuildQueue(PulseQueue):

    def __init__(self, exchange_name='exchange/build/normalized',
                 routing_key='#', **kwargs):

        PulseQueue.__init__(self, exchange_name=exchange_name,
                            routing_key=routing_key, **kwargs)


class TaskCompletedQueue(PulseQueue):

    def __init__(self, exchange_name='exchange/taskcluster-queue/v1/task-completed',
                 routing_key='#', **kwargs):
        PulseQueue.__init__(self, exchange_name=exchange_name,
                            routing_key=routing_key, **kwargs)
