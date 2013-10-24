#!/usr/bin/env bash

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

DIR_TEST_ENV="test/venv"
DIR_JENKINS_ENV=jenkins-env
VERSION_VIRTUALENV=1.9.1

echo "Checking patches"
./test/check_patches.sh || exit $?

if [ -d "$DIR_JENKINS_ENV" ] && [ -z $CI ]; then
  echo "Jenkins environment already exists!"
  while true; do
    read -p "Would you like to recreate it? " yn
    case $yn in
      [Yy]* ) echo "Running setup"; ./setup.sh $DIR_JENKINS_ENV; break;;
      [Nn]* ) break;;
      * ) echo "Please answer yes or no.";;
    esac
  done
else
  echo "Running setup"
  ./setup.sh $DIR_JENKINS_ENV
fi

echo "Starting Jenkins"
./start.sh > jenkins.out &
sleep 60

# Check if environment exists, if not, create a virtualenv:
if [ -d $DIR_TEST_ENV ]
then
  echo "Using virtual environment in $DIR_TEST_ENV"
else
  echo "Creating a virtual environment (version ${VERSION_VIRTUALENV}) in ${DIR_TEST_ENV}"
  curl https://raw.github.com/pypa/virtualenv/${VERSION_VIRTUALENV}/virtualenv.py | python - --no-site-packages $DIR_TEST_ENV
fi
. $DIR_TEST_ENV/bin/activate || exit $?

pip install selenium
python test/configuration/save_config.py

echo "Killing Jenkins"
pid=$(lsof -i:8080 -t); kill -TERM $pid || kill -KILL $pid

git --no-pager diff --exit-code
