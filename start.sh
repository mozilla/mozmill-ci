#!/usr/bin/env bash

JENKINS_VERSION=1.456
JENKINS_URL="http://mirrors.jenkins-ci.org/war/$JENKINS_VERSION/jenkins.war"
JENKINS_WAR=jenkins.war

export JENKINS_HOME=$(dirname $BASH_SOURCE)/jenkins-master


if [ ! -e $JENKINS_WAR ]; then
  echo "Downloading Jenkins $JENKINS_VERSION from $JENKINS_URL"
  curl --location $JENKINS_URL -o $JENKINS_WAR
fi

# TODO: Start Jenkins as daemon
java -jar $JENKINS_WAR

