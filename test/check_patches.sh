#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

DIR_BASE=$(cd $(dirname ${BASH_SOURCE}); pwd)
for ENVIRONMENT in staging production ; do
  echo "Testing patch for $ENVIRONMENT"
  patch --directory=$DIR_BASE/.. --dry-run -p1 <$DIR_BASE/../config/$ENVIRONMENT/jenkins.patch || exit $?
done
