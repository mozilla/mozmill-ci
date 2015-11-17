# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


class Enum(tuple):
    __getattr__ = tuple.index


# Build exit code as defined by buildbot
# From: https://github.com/mozilla/treeherder/blob/master/treeherder/etl/buildbot.py#L3
BuildExitCode = Enum([
    'success',     # 0
    'testfailed',  # 1
    'busted',      # 2
    'skipped',     # 3
    'exception',   # 4
    'retry',       # 5
    'usercancel'   # 6
])
