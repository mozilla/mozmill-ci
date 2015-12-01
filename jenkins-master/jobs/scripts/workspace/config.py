# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os

here = os.path.dirname(os.path.abspath(__file__))


config = {
    'test_types': {
        'functional': {
            'harness_config': os.path.join('firefox_ui_tests', 'qa_jenkins.py'),
            'harness_script': os.path.join('firefox_ui_tests', 'functional.py'),
            'treeherder': {
                'group_name': 'Firefox UI Functional Tests',
                'group_symbol': 'Fxfn',
                'job_name': 'Firefox UI Functional Tests ({locale})',
                'job_symbol': '{locale}',
                'tier': 3,
                'artifacts': {
                    'log_info.log': os.path.join(here, 'build', 'upload', 'logs', 'log_info.log'),
                    'report.html': os.path.join(here, 'build', 'upload', 'reports', 'report.html'),
                },
                'log_reference': 'log_info.log',
            },
        },
        'update': {
            'harness_config': os.path.join('firefox_ui_tests', 'qa_jenkins.py'),
            'harness_script': os.path.join('firefox_ui_tests', 'update.py'),
            'treeherder': {
                'group_name': 'Firefox UI Update Tests - {update_channel}',
                'group_symbol': 'Fxup-{update_channel}',
                'job_name': 'Firefox UI Update Tests - {update_channel} {locale}-{update_number}',
                'job_symbol': '{locale}-{update_number}',
                'tier': 3,
                'artifacts': {
                    'log_info.log': os.path.join(here, 'build', 'upload', 'logs', 'log_info.log'),
                    'report.html': os.path.join(here, 'build', 'upload', 'reports', 'report.html'),
                    # TODO: Bug 1210753: Move generation of log as option to mozharness
                    'http.log': os.path.join(here, 'build', 'http.log'),
                },
                'log_reference': 'log_info.log',
            },
        },
    },
}
