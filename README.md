# Mozmill CI
With the Mozmill CI project we aim to get a fully automated testing cycle implemented for testing Firefox in the Mozilla QA compartment. Therefore the [Mozilla Pulse](http://pulse.mozilla.org/) message broker and [Jenkins](http://jenkins-ci.org/) are used.

## Setup
Before you can start the system the following commands have to be performed:

    git clone git://github.com/whimboo/mozmill-ci.git
    cd mozmill-ci
    ./setup.sh

Make sure that you have the Python header files installed. If those are not present, install those:

    Ubuntu:       Install the package via: apt-get install python-dev
    OSX, Windows: Install the latest [Python 2.7](http://www.python.org/getit/)

## Startup
The two components (Pulse consumer and Jenkins master) have to be started separately in two different terminals. As first step we have to setup the Jenkins master:

    ./start.sh

Once Jenkins has been fully started, you will have to configure your system now. Therefore open `http://localhost:8080/configure` via your web browser. In the section "Global properties" update the following entries:

    MOZMILL_VERSION (Version of Mozmill to use)
    NOTIFICATION_ADDRESS (Email address of the notification emails)

After you are done with the configuration open the `+admin` view and execute all of the listed jobs once. Also update the `Jenkins URL` of the master to a public accessible IP or DNS name, so that slave nodes can successfully connect.

Now you can start the Pulse consumer which pushes requests for jobs through the Jenkins API to the master:

    source jenkins-env/bin/activate
    ./pulse.py config/example_daily.cfg

Please keep in mind that you should create your own configuration file before you start the consumer and setup the wanted builds appropriately.

## Adding new Nodes
To add Jenkins slaves to your master you have to create new nodes. You can use one of the example nodes (Windows XP and Ubuntu) as a template. Once done the nodes have to be connected to the master. Therefore Java has to be installed on the node first.

### Windows:
Go to [www.java.com/download/](http://www.java.com/download/) and install the latest version of Java JRE. Also make sure that the UAC is completely disabled, and the screensaver and any energy settings have been turned off.

### Linux (Ubuntu):
Open the terminal or any other package manager and install the following packages:

    sudo add-apt-repository ppa:ferramroberto/java
    sudo apt-get update
    sudo apt-get install sun-java6-jre sun-java6-plugin

Also make sure that the screensaver and any energy settings have been turned off.

After Java has been installed open the appropriate node within Jenkins from the nodes web browser like:

    http://IP:8080/computer/windows_xp_32_01/

Now click the `Launch` button and the node should automatically connect to the master. It will be used once a job for this type of platform has been requested by the Pulse consumer.

## Using the Jenkins master as executor
If you want that the master node also executes jobs you will have to update its labels and add/modify the appropriate platforms, e.g. 'master mac 10.7 64bit' for MacOS X 10.7.

## Job priorities
To allow Mozmill tests to be executed immediately for release and beta builds priorities are necessary. The same applies to the type of testrun, where some have higher priority.

    trigger_ondemand            = 1099

    ondemand                    = 1000
    release-mozilla-release     =  800
    release-mozilla-esr(CUR)    =  700
    release-mozilla-esr(LAST)   =  600
    release-mozilla-beta        =  500
    mozilla-esr                 =  400
    mozilla-central             =  300
    mozilla-aurora              =  200
    mozilla-1.9.2               =  100

    update                      =   60
    functional                  =   50
    endurance                   =   40
    remote                      =   30
    addon                       =   20
    l10n                        =   10

The higher the priority value, the higher the priority the job will have in the queue. For example, mozilla-central_endurance will have a value of 340 (300 + 40) and will therefore be executed before mozilla-aurora_endurance, which will have a value of 240 (200 + 40).

## Merging branches
The main development on the Mozmill CI code happens on the master branch. In not yet specified intervals we are merging changesets into the staging branch. It is used for testing all the new features before those go live on production. When running those merge tasks you will have to obey the following steps:

1. Select the appropriate target branch
2. Run 'git rebase master' for staging or 'git rebase staging' for production
3. Run 'git pull' for the remote branch you want to push to
4. Ensure the merged patches are on top of the branch
5. Ensure that the Jenkins patch can be applied by running 'patch -p1 <config/%BRANCH%/jenkins.patch'
6. Run 'git push' for the remote branch

For emergency fixes we are using cherry-pick to port individual fixes to the staging and production branch:

1. Select the appropriate target branch
2. Run 'git cherry-pick %changeset%' to pick the specific changeset for the current branch
3. Run 'git push' for the remote branch

Once the changes have been landed you will have to update the staging or production machines. Run the following steps:

1. Run 'git reset --hard' to remove the locally applied patch
2. Pull the latest changes with 'git pull'
3. Apply the Jenkins patch with 'patch -p1 <config/%BRANCH%/jenkins.patch'
4. Restart Jenkins 

## Running on-demand tests
1. Navigate to your Jenkins instance: http://IP:8080
2. Open the +admin tab and look for the 'trigger-ondemand' row
3. Click the green arrow button, 'Schedule a Build'
4. Upload your ondemand.cfg file (see examples in [./config/ondemand/](https://github.com/whimboo/mozmill-ci/tree/master/config/ondemand))
5. Click 'Back to Dashboard' link and open the @ondemand tab

If you see an ondemand_* testrun in the middle is blinking and the nodes on the left are not 'idle', your testrun is executing. The results should appear in your dashboard when complete.

## Uninterrupted Aurora update tests
After a Firefox release, the source code is merged from default -> aurora and from aurora -> beta.
At this point the Aurora updates are temporarily disabled. In order for the Aurora update tests to
continue, the channel must be changed from 'aurora' to 'auroratest'. You can do this by configuring
the mozilla-aurora_update job via the Jenkins web console and changing the default value for the
CHANNEL parameter. Note that if a new release of Mozmill CI is made, the default will reset back to
'aurora'.
