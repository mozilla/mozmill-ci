# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse


class JenkinsDefaultValueAction(argparse.Action):
    """Fix default values of arguments as set by Jenkins

    If a parametrized job is used in Jenkins the used parameters always have
    to be passed into the shell script. There is no known way yet to do it conditionally.
    As result we have chosen "None" as default value, so that it can easily be reset.

    """
    def __call__(self, parser, namespace, values, option_string=None):
        if type(values) is str:
            values = values if values != 'None' else None
        elif type(values) is list:
            values = [value if value != 'None' else None for value in values]

        setattr(namespace, self.dest, values)
