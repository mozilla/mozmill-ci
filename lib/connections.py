# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from kombu import Connection


class PulseConnection(Connection):

    def __init__(self, hostname='pulse.mozilla.org', port=5671,
                 virtual_host='/', ssl=True, **kwargs):
        Connection.__init__(self, hostname=hostname, port=port,
                            virtual_host=virtual_host, ssl=ssl,
                            **kwargs)
