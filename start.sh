#!/usr/bin/env bash

BASE=$(dirname $BASH_SOURCE)/jenkins-master
WAR=jenkins.war

URL_JENKINS="http://mirrors.jenkins-ci.org/war/latest/jenkins.war"

export JENKINS_HOME=$BASE


if [ ! -e $WAR ]; then
  curl --location $URL_JENKINS -o $WAR
fi

# TODO: Start Jenkins as daemon
java -jar $WAR

