Mozmill CI
==========

With the Mozmill CI project we aim to get a fully automated testing cycle implemented for testing Firefox in the Mozilla QA compartment. Therefore the [Mozilla Pulse](http://pulse.mozilla.org/) message broker and [Jenkins](http://jenkins-ci.org/) are used.

Setup
-----
Before you can start the system the following commands have to be performed:

    git clone git://github.com/whimboo/mozmill-ci.git
    cd mozmill-ci
    ./setup/configure.sh

Startup
-------
The two components (Pulse consumer and Jenkins master) have to be started separately in two different terminals. As first step we have to setup the Jenkins master:

    ./start.sh

Once Jenkins has been fully started, open `http://localhost:8080/` via your web browser. Open the `+admin` view and execute all of the listed jobs once. Also update the `Jenkins URL` of the master to a public accessible IP or DNS name, so that slave nodes can successfully connect.

Now you can start the Pulse consumer which pushes requests for jobs through the Jenkins API to the master:

    source jenkins-env/bin/activate
    ./pulse.py config/example_daily.cfg

Please keep in mind that you should create your own configuration file before you start the consumer and setup the wanted builds appropriately.

Adding new Nodes
----------------
To add Jenkins slaves to your master you have to create new nodes. You can use one of the example nodes (Windows XP and Ubuntu) as a template. Once done the nodes have to be connected to the master. Therefore Java has to be installed on the node first.

Windows:

Go to [www.java.com/download/](http://www.java.com/download/) and install the latest version of Java JRE. Also make sure that the UAC is completely disabled, and the screensaver and any energy settings have been turned off.

Linux (Ubuntu):

Open the terminal or any other package manager and install the following packages:

    sudo add-apt-repository ppa:ferramroberto/java
    sudo apt-get update
    sudo apt-get install sun-java6-jre sun-java6-plugin

Also make sure that the screensaver and any energy settings have been turned off.

After Java has been installed open the appropriate node within Jenkins from the nodes web browser like:

    http://IP:8080/computer/windows_xp_32_01/

Now click the `Launch` button and the node should automatically connect to the master. It will be used once a job for this type of platform has been requested by the Pulse consumer.

Using the Jenkins master as executor
------------------------------------
If you want that the master node also executes jobs you will have to update its labels and add/modify the appropriate platforms, e.g. 'master mac 10.7 64bit' for MacOS X 10.7.

Running on-demand tests
-------------------------------
1. Navigate to your Jenkins instance: http://IP:8080
2. Open the +admin tab and look for the 'trigger-ondemand' row
3. Click the green arrow button, 'Schedule a Build'
4. Upload your ondemand.cfg file (see examples in [./config/ondemand/](https://github.com/whimboo/mozmill-ci/tree/master/config/ondemand))
5. Click 'Back to Dashboard' link and open the @ondemand tab

If you see an ondemand_* testrun in the middle is blinking and the nodes on the left are not 'idle', your testrun is executing. The results should appear in your dashboard when complete.
