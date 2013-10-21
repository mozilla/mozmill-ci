# Mozmill CI
With the Mozmill CI project we aim to get a fully automated testing cycle
implemented for testing Firefox in the Mozilla QA compartment. We therefore use
the [Mozilla Pulse](http://pulse.mozilla.org/) message broker to identify when
new builds are available, and [Jenkins](http://jenkins-ci.org/) to download the
builds and run the tests.

## Setup
Before you can start the system the following commands have to be performed:

```bash
git clone git://github.com/mozilla/mozmill-ci.git
cd mozmill-ci
./setup.sh
```

You will need to have the Python header files installed:

* Ubuntu: Install the package via: `apt-get install python-dev`
* OSX, Windows: Install the latest [Python 2.7](http://www.python.org/getit/)

## Startup
To start Jenkins simply run `./start.py` from the mozmill-ci directory. You
can tell when Jenkins is running by looking out for "Jenkins is fully up and
running" in the console output. You will also be able to view the web dashboard
by pointing your browser at http://localhost:8080/

If this is the first time you've started Jenkins, or your workspaces have
recently been deleted, you will need to run some admin jobs to finish the
setup. Open http://localhost:8080/view/+admin/ and schedule builds of the
following jobs *in order* by clicking the clock icon in the last column.

1. get_mozmill-environments
2. get_mozmill-tests

You should *not* build the trigger-ondemand job.

If you want to automatically trigger jobs as builds become available, start the
Pulse consumer which uses the Jenkins API (in a separate terminal):

```bash
source jenkins-env/bin/activate
./pulse.py config/example_daily.cfg
```

You should create your own configuration file before you start the consumer and
set the wanted builds appropriately.

## Changing the version of Mozmill
If you need to specify an alternate version of Mozmill to use, you can change
the value associated with the `MOZMILL_AUTOMATION_VERSION` environment
variable. This can be found in http://localhost:8080/configure under the
section headed "Global properties".

## E-mail notifications
By default there is no e-mail address for notifications to be sent. In our
production system we have these sent to the mozmill-ci mailing list. If you
would like to enable notifications locally (this can be useful during testing)
you will need to specify the recipient e-mail address for the
`NOTIFICATION_ADDRESS` environment variable. This can be found in
http://localhost:8080/configure under the section headed "Global properties".

## Jenkins URL
If you intend to connect to this Jenkins instance from another machine (for
example connecting additional nodes) you will need to update the `Jenkins URL`
to the IP or DNS name. This can be found in http://localhost:8080/configure
under the section headed "Jenkins Location".

## Adding new Nodes
To add Jenkins slaves to your master you have to create new nodes. You can use
one of the example nodes (Windows XP and Ubuntu) as a template. Once done the
nodes have to be connected to the master. Therefore Java has to be installed on
the node first.

### Windows:
Go to [www.java.com/download/](http://www.java.com/download/) and install the
latest version of Java JRE. Also make sure that the UAC is completely disabled,
and the screensaver and any energy settings have been turned off.

### Linux (Ubuntu):
Open the terminal or any other package manager and install the following
packages:

```bash
sudo add-apt-repository ppa:webupd8team/java
sudo apt-get update
sudo apt-get install oracle-java7-installer
```

Also make sure that the screensaver and any energy settings have been turned
off.

After Java has been installed open the appropriate node within Jenkins from the
nodes web browser like:

    http://IP:8080/computer/windows_xp_32_01/

Now click the `Launch` button and the node should automatically connect to the
master. It will be used once a job for this type of platform has been requested
by the Pulse consumer.

## Using the Jenkins master as executor
If you want that the master node also executes jobs you will have to update its
labels and add/modify the appropriate platforms, e.g. `master mac 10.7 64bit`
for Mac OS X 10.7.

## Job priorities
To allow Mozmill tests to be executed immediately for release and beta builds
priorities are necessary. The same applies to the type of testrun, where some
have higher priority.

<table>
    <tr><td>trigger_ondemand</td><td>1099</td></tr>
</table>
<table>
    <tr><td>ondemand</td><td>1000</td>
    <tr><td>release-mozilla-release</td><td>800</td>
    <tr><td>release-mozilla-esr(CUR)</td><td>700</td>
    <tr><td>release-mozilla-esr(LAST)</td><td>600</td>
    <tr><td>release-mozilla-beta</td><td>500</td>
    <tr><td>mozilla-esr</td><td>400</td>
    <tr><td>mozilla-central</td><td>300</td>
    <tr><td>mozilla-aurora</td><td>200</td>
    <tr><td>mozilla-project</td><td>100</td>
</table>
<table>
    <tr><td>update</td><td>60</td>
    <tr><td>functional</td><td>50</td>
    <tr><td>endurance</td><td>40</td>
    <tr><td>remote</td><td>30</td>
    <tr><td>addon</td><td>20</td>
    <tr><td>l10n</td><td>10</td>
</table>

The higher the priority value, the higher the priority the job will have in the
queue. For example, mozilla-central_endurance will have a value of 340 (300 +
40) and will therefore be executed before mozilla-aurora_endurance, which will
have a value of 240 (200 + 40).

## Testing changes
In order to check that patches will apply and no Jenkins configuration changes
are missing from your changes you can run the `run_tests.sh` script. This uses
[Selenium](http://code.google.com/p/selenium/) and
[PhantomJS](http://phantomjs.org/) to save the configuration for each job and
reports any unexpected changes. Note that you will need to
[download](http://phantomjs.org/download.html) PhantomJS and put it in your
path in order for these tests to run.

## Merging branches
The main development on the Mozmill CI code happens on the master branch. In
not yet specified intervals we are merging changesets into the staging branch.
It is used for testing all the new features before those go live on production.
When running those merge tasks you will have to obey the following steps:

1. Select the appropriate target branch
2. Run 'git rebase master' for staging or 'git rebase staging' for production
3. Run 'git pull' for the remote branch you want to push to
4. Ensure the merged patches are on top of the branch
5. Ensure that the Jenkins patch can be applied by running 'patch --dry-run -p1
 <config/%BRANCH%/jenkins.patch'
6. Run 'git push' for the remote branch

For emergency fixes we are using cherry-pick to port individual fixes to the
staging and production branch:

1. Select the appropriate target branch
2. Run 'git cherry-pick %changeset%' to pick the specific changeset for the
current branch
3. Run 'git push' for the remote branch

Once the changes have been landed you will have to update the staging or
production machines. Run the following steps:

1. Run 'git reset --hard' to remove the locally applied patch
2. Pull the latest changes with 'git pull'
3. Apply the Jenkins patch with 'patch -p1 <config/%BRANCH%/jenkins.patch'
4. Restart Jenkins

## Running on-demand tests
1. Open the +admin tab in your Jenkins instance:
http://localhost:8080/view/+admin/
2. Find the 'trigger-ondemand' job and click the clock icon with tooltip
'Schedule a Build'
4. Upload your ondemand.cfg file (see examples in
[./config/ondemand/](https://github.com/whimboo/mozmill-ci/tree/master/config/ondemand))
5. Click 'Back to Dashboard' link and open the @ondemand tab

If you see an ondemand_* testrun in the middle is blinking and the nodes on the
left are not 'idle', your testrun is executing. The results should appear in
your dashboard when complete.

## Running tests for builds of project branches
Beside the mozilla-central branch also project branches exists, which are used by
developers for new feature integration work. You will be able to run tests for those
builds by executing one of the 'project_*' jobs which can be found under the
'project' view. Keep in mind that you will have to enter the branch name, e.g. 'ux'
for the UX branch.

## Uninterrupted Aurora update tests
After a Firefox release, the source code is merged from default -> aurora and
from aurora -> beta. At this point the Aurora updates are temporarily disabled.
In order for the Aurora update tests to continue, the channel must be changed
from 'aurora' to 'auroratest'. You can do this by configuring the
mozilla-aurora_update job via the Jenkins web console and changing the default
value for the CHANNEL parameter. Note that if a new release of Mozmill CI is
made, the default will reset back to 'aurora'.

## Troubleshooting
If Jenkins fails to start it may be due to the default memory requirements. If
your machine has less than 2GB of available memory you may need to reduce the
values for `Xms` and `Xmx` in `start.py`

Due to [issue #125](https://github.com/mozilla/mozmill-ci/issues/125)
you may experience issues saving the Jenkins configuration. If so, try
unchecking the 'Node Offline Email Notification' on the node configuration and
submit your configuration changes again. You should then be able to check the
box again and save.
