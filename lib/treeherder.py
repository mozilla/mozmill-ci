# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


from thclient import TreeherderClient


def get_revision_hash(host, project, revision):
    """Retrieve the Treeherder's revision hash for a given revision.

    :param host: URL of the Treeherder instance.
    :param project: The project (branch) to use.
    :param revision: The revision to get the hash for.
    """
    client = TreeherderClient(host=host, protocol='https')
    resultsets = client.get_resultsets(project, revision=revision)

    return resultsets[0]['revision_hash']
