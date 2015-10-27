# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

here = os.path.dirname(os.path.abspath(__file__))


config = {
    'test_types': {
        'functional': {
            'treeherder': {
                'group_name': 'Firefox UI Tests - Functional',
                'group_symbol': 'Ff',
                'job_name': '{locale}',
                'job_symbol': '{locale}',
                'tier': 3,
            },
            'logs': {
                'gecko.log': os.path.join(here, 'upload', 'logs', 'gecko.log'),
                'tbpl.log': os.path.join(here, 'upload', 'logs', 'tbpl.log'),
            }
        },
        'update': {
            'treeherder': {
                'group_name': 'Firefox UI Tests - Update',
                'group_symbol': 'Fu',
                'job_name': '{locale}-{update_number}',
                'job_symbol': '{locale}-{update_number}',
                'tier': 3,
            },
            'logs': {
                # Currently we don't have a gecko.log because we log to the console (bug 1174766)
                # 'gecko': os.path.join(here, 'build', 'upload', 'logs', 'gecko.log'),
                'http.log': os.path.join(here, 'upload', 'logs', 'http.log'),
                'tbpl.log': os.path.join(here, 'upload', 'logs', 'tbpl.log'),
            }
        },
    },
}
