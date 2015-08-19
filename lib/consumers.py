# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from kombu.mixins import ConsumerMixin


class PulseConsumer(ConsumerMixin):

    def __init__(self, connection):
        self.connection = connection

        self._queues = []

    @property
    def queues(self):
        """List of queues used by worker.
        Multiple queues are used to track multiple routing keys.
        """
        return self._queues

    def add_queue(self, queue):
        self._queues.append(queue)

    def get_consumers(self, consumer, channel):
        """Implement parent's method called to get the list of consumers"""
        # Set prefetch_count to 1 to avoid blocking other workers
        channel.basic_qos(prefetch_size=0, prefetch_count=1, a_global=False)

        return [consumer(queues=[q], callbacks=[q.process_message]) for q in self.queues]
