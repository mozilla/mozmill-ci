#!/usr/bin/env bash

PYTHON_VERSION=$(python -c "import sys;print sys.version[:3]")

BASE_DIR=$(dirname $(cd $(dirname $BASH_SOURCE); pwd))
ENV_DIR=$BASE_DIR/jenkins-env

SETUP_DIR=$BASE_DIR/setup
TMP_DIR=$SETUP_DIR/tmp

URL_VIRTUALENV=https://bitbucket.org/ianb/virtualenv/raw/1.5.2/virtualenv.py


if [ -e $ENV_DIR ]; then
  rm -r $ENV_DIR
fi

echo "Fetching latest version of virtualenv and creating new environment"
mkdir $TMP_DIR && curl $URL_VIRTUALENV > $TMP_DIR/virtualenv.py
python $TMP_DIR/virtualenv.py --no-site-packages $ENV_DIR

echo "Activating the new environment"
source $ENV_DIR/bin/activate
if [ ! -n "${VIRTUAL_ENV:+1}" ]; then
    echo "### Failure in activating the new virtual environment: '$ENV_DIR'"
    rm -r $ENV_DIR $TMP_DIR
    exit 1
fi

echo "Installing required Python modules"
pip install -r $SETUP_DIR/requirements.txt

echo "Deactivating the environment"
deactivate

echo "Successfully created the Jenkins environment: '$ENV_DIR'"
echo "Please see 'mozmill-env/README' for the setup of the Mozmill Environment"

rm -r $TMP_DIR
