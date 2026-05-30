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
# Add a Forgejo team for every possible gitlab group member access level
#add_empty_teams_to_organizations=True <True / False>
# Add all Forgejo organisation teams to the repos owned by it, not just those with current users 
#add_empty_teams_to_repos=True <True / False>

# If True, users found matching ^project_[0-9]{2}_bot_[a-zA-Z0-9]{32}$ or in list ignored_gitlab_system_users will NOT be imported, but generate a warning instead
#ignore_gitlab_system_users=False <True / False>
#ignored_gitlab_system_users="GitLab-Admin-Bot,ghost,support-bot,alert-bot,GitlabDuo"

# When creating collaborators, are teams permitted to utilise the Forgejo nearest neighbor permission?
#allow_fuzzy_teams=False
# When creating collaborators, are users permitted to utilise the Forgejo nearest neighbor permission?
#allow_fuzzy_users=False
# If True, allow the closest lower permission defined Forgejo team to be used in lieu (lower have precedence over higher)
#allow_fuzzy_auth_downgrade=False
# If True, allow the closest higher permission defined Forgejo team to be used in lieu (lower have precedence over higher)
#allow_fuzzy_auth_upgrade=False

# Overrides for organization team names (for their gitlab equivalent)
#org_team_maintainers_name=Maintainers
#org_team_developers_name=Developers
#org_team_reporters_name=Reporters
#org_team_guests_name=Guests
# Overrides for organization team descriptions
#org_team_owners_description=Owners
#org_team_maintainers_description=Maintainers
#org_team_developers_description=Developers
#org_team_reporters_description=Reporters
#org_team_guests_description=Guests

# Gitlab website url
gitlab_url = https://gitlab.example.com <http[s]://hostname[:port][/path]>
# Either a Gitlab token OR admin user and password are required for migrate, but push mirrors requires user and password at present
gitlab_token = <your-gitlab-token>
gitlab_admin_user = <gitlab-admin-user>
gitlab_admin_pass = <your-gitlab-password>
#gitlab_sync_connection_type = https <ssh/https>

forgejo_url = https://forgejo.example.com
# Either a Forgejo token OR admin user and password are required for migrate, but push mirrors requires user and password at present
forgejo_token = <your-forgejo-token>
forgejo_admin_user = <forgejo-admin-user>
forgejo_admin_pass = <your-forgejo-password>


# if your forgejo instance requires client authentication, provide the paths to the cert and key files below
# If forgejo_client_auth_cert is provided, client authentication is switched on
#forgejo_client_auth_cert = /path/to/forgejo_client_auth_cert.pem
#forgejo_client_auth_key = /path/to/forgejo_client_auth_key.pem

# If your gitlab instance requires client authentication, 
# uncomment these parameters, and provide the appropriate paths
# If gitlab_client_auth_cert is provided, client authentication is switched on
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
* Added support for creating Organization Teams and Collaborators to match Gitlab users based on gitlab access level.

Note:
* I have added warnings where users are found that I think are likely to be gitlab system users. They are imported anyway, just in case, but you're made aware.
* If a user fails to import, e.g. ghost is a reserved username in forgejo, then that doesn't stop the script trying to add that user to any groups / teams which makes for some logging noise

The parent was a fork of [gitlab_to_gitea](https://git.autonomic.zone/kawaiipunk/gitlab-to-gitea.git), with less features (this script does not import issues, milestones and labels)
