#!/usr/bin/env bash

JENKINS_VERSION=1.455
JENKINS_URL="http://mirrors.jenkins-ci.org/war/$JENKINS_VERSION/jenkins.war"
JENKINS_WAR=jenkins.war

export JENKINS_HOME=$(dirname $BASH_SOURCE)/jenkins-master


echo "Downloading Jenkins $JENKINS_VERSION from $JENKINS_URL"
curl --location $JENKINS_URL -z $JENKINS_WAR -o $JENKINS_WAR

source jenkins-env/bin/activate

# TODO: Start Jenkins as daemon
java -jar -Xms2g -Xmx2g -XX:MaxPermSize=512M -Xincgc $JENKINS_WAR

