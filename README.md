# Gitlab to Forgejo migration script

## Preamble

This script uses the Gitlab API and a combination of [pyforgejo](https://codeberg.org/harabat/pyforgejo) and python `requests` to migrate all data from Gitlab to Forgejo.

This script supports migration of:

* Repositories & Wiki (fork status is lost)
* Users (no profile pictures)
* Groups
* Public SSH keys

Tested with Gitlab Version 17.2.1 and Forgejo Version 8.0.0

## Usage

### How to use with venv

To keep your local system clean, it is preferrable to use a virtual environment.
You can follow these steps:

N.b, on windows, run ```migration/bin/activate```, not ```source migration/bin/activate```
```bash
python3 -m venv migration
source migration/bin/activate
python3 -m pip install -r requirements.txt
```

and you call the scripts using `--help`:

* `./migrate.py --help`
* `./create_push_mirrors.py --help`

### ini file

You need to create a configuration file called `.migrate.ini` and store it in the same directory of the script.  
:bulb: `.migrate.ini` is listed in `.gitignore`.

```ini
[migrate]
gitlab_url = https://gitlab.example.com
gitlab_token = <your-gitlab-token>
gitlab_admin_user = <gitlab-admin-user>
gitlab_admin_pass = <your-gitlab-password>
forgejo_url = https://forgejo.example.com
# Must be a full access read and write permissions token
forgejo_token = <your-forgejo-token>
# user and pass are Not needed for the migrate.py script
forgejo_admin_user = <forgejo-admin-user>
forgejo_admin_pass = <your-forgejo-password>

# If your gitlab instance requires client authentication, 
# uncomment these parameters, and provide the appropriate paths
#gitlab_client_auth_cert = /path/to/gitlab_client_auth_cert.pem
#gitlab_client_auth_key = /path/to/gitlab_client_auth_key.pem
```

### Credits and fork information

This is a fork of https://github.com/GEANT/gitlab-to-forgejo.

Changes:
* I've re-added support for issues, milestones and labels, though don't use these myself.
* I've added support for gitlab client certificate authentication
* I've added support for forgejo client certificate authentication
* I've updated this script to use the new API for forgejo (2.0+).
* I tried to make minimal changes initially, but in the end, I have refactored a bit, but the program flow remains intentionally identical. It would be fairy easy to refactor this further in to a series of classes, allowing future addition of any source system of your choice.
* Added support for user GPG key import, though don't use these myself.

Note:
* I have added warnings where users are found that I think are likely to be gitlab system users. They are imported anyway, just in case, but you're made aware.
* If a user fails to import, e.g. ghost is a reserved username in forgejo, then that doesn't stop the script trying to add that user to any groups / teams which makes for some logging noise

The parent was a fork of [gitlab_to_gitea](https://git.autonomic.zone/kawaiipunk/gitlab-to-gitea.git), with less features (this script does not import issues, milestones and labels)
