#!/usr/bin/env bash

# URL_MOZILLA_PULSE='http://hg.mozilla.org/users/clegnitto_mozilla.com/mozillapulse/archive/tip.zip'
URL_VIRTUALENV=https://bitbucket.org/ianb/virtualenv/raw/1.5.2/virtualenv.py

ENV_DIR=jenkins-env
PYTHON_VERSION=$(python -c "import sys;print sys.version[:3]")

if [ -e $ENV_DIR ]; then
  rm -r $ENV_DIR
fi

echo "Fetching latest version of virtualenv and creating new environment"
mkdir tmp && curl $URL_VIRTUALENV > tmp/virtualenv.py
python tmp/virtualenv.py --no-site-packages $ENV_DIR

echo "Activating the new environment"
source $ENV_DIR/bin/activate
if [ ! -n "${VIRTUAL_ENV:+1}" ]; then
    echo "### Failure in activating the new virtual environment: '$ENV_DIR'"
    rm -r tmp $ENV_DIR
    exit 1
fi

echo "Installing required Python modules"
pip install -r requirements.txt

echo "Deactivating the environment"
deactivate

echo "Successfully created the environment: '$ENV_DIR'"

rm -r tmp
