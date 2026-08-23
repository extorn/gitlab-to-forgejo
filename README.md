# Automated Migration to Forgejo for Users,Organizations,Teams,Repositories,...

*   Currently only GitLab is implemented as a data source, but implementing support for others in a modular way is possible and relatively trivial, even for a non python developer such as myself. See [README-Developers.md](./README-Developers.md)

## Preamble

This script uses Source System APIs and a combination of [pyforgejo](https://codeberg.org/harabat/pyforgejo) and python `requests` (where necessary) to migrate all data from that system to Forgejo.

This script currently supports GitLab, including migration of:

Repositories

*   Code, Issues, Labels, Milestones, Pull requests, Releases, Mirror & Wiki (this is part of the internal Forgejo migration)
*   All Accessors (i.e. users) - assigned to Teams and given access to match your mapping specification

Users

*   Public SSH keys, PGP Keys
*   Avatars for any **NEWLY** (because it requires the script to login as that user to upload the avatar) created users
*   _all users will have a temporary password assigned and need to change it on first use_

Groups

*   Both organisational Groups and team Groups as Forgejo Organizations and Forgejo Teams respectively.
*   Roles are defined according to your configured specification, mapping Gitlab users with any given source access level to those roles as you decide

Tested with GitLab Version 18.11 and Forgejo Version 15.0.2

## Note

The code has been written in such a way as to facilitate painless extension to load from **any** source control system of your choice by implementing only the code to load the data from that system.

## **Usage**

### How to use with venv

To keep your local system clean, it is preferrable to use a virtual environment.
You can follow these steps:

N.b, on windows in cmd or powershell, run `migration/bin/activate`, not `source migration/bin/activate`

```
python3 -m venv migration
source migration/bin/activate
python3 -m pip install -r requirements.txt
```

and you call the scripts using `--help`:

*   `./migrate.py --help`
*   `./purge_forgejo.py --help` **Note**: Use this to wipe certain types of, or all, data from the .migrate.ini defined Forgejo instance
*   `./create_push_mirrors.py --help`  **NOTE**: **I have not used this script, it might work, it might not. It ONLY supports GitLab**

## Configuration Files

### **forgejo\_user\_roles.yaml**

This file contains a list of all supported roles within Forgejo as defined by this script (you are not limited to any number by Forgejo itself.

Please alter the values in this file to match your personal configuration desires, I've tried to set what I thought looked reasonable to me, but I'm confident you may wish to change any or all values. You can add as many roles as you wish or have as few as you wish with the caveat that there currently _**MUST**_ be a role with a team named _**Owners**_.

### **gitlab\_forgejo\_roles\_map.yaml**

This file contains a list of mappings from gitlab access levels to
Forgejo roles as defined in the forgejo\_user\_roles.yaml file. Feel free
to change the values in this, add more or delete them as you wish to match
your requirements.

### **.migrate.ini file**

You need to create a configuration file called `.migrate.ini` and store it in the same directory of the script.

:bulb:
`.migrate.ini` is listed in `.gitignore`.

```
###
### These are the settings controlling the migration process from
### a source system such as GitLab into Forgejo
###
### Use:
###
### 1. Default values are shown in commented out options
### 2. Any settings NOT commented out MUST be set to match your requirements
### 3. <...> is used to give a clue as to value e.g. <True|False>
### 4. Comments on the same line as a configuration option are not supported
###    e.g.
###    input -> my_setting=some_value # A comment
###    read as -> my_setting="some_value # A comment"
### 5. Where there is a default, I recommend copy and pasting that directly below, uncommenting it, then
###    altering it to suit so you always know at a glance what the default was



[forgejo]

# the yaml file where all the user roles and permissions are defined
# These roles are used for both users and teams, and eventually for a migration, you'll be able to pick how you map to them using the source access levels to forgejo roles mapping file.
#forgejo_user_roles_file_path=forgejo_user_roles.yaml
# Url where you have the sign in link on your Forgejo instance
forgejo_url = https://forgejo.example.com
### A Forgejo application token - with maximum permissions (for migration at least).
forgejo_token = <your-forgejo-token>


### if your forgejo instance requires client authentication, provide the paths to the cert and key files below.
### If forgejo_client_auth_cert is provided, client authentication is switched on
#forgejo_client_auth_cert = /path/to/forgejo_client_auth_cert.pem
#forgejo_client_auth_key = /path/to/forgejo_client_auth_key.pem
# Max records to retrieve in a single API call to Forgejo
#forgejo_api_max_page_size=50


[gitlab]

# GitLab website url
gitlab_url = https://gitlab.example.com <http[s]://hostname[:port][/path]>
### Either a GitLab token OR admin user and password are required for migrate, but push mirrors requires user and password at present
gitlab_token = <your-gitlab-token>
gitlab_admin_user = <gitlab-admin-user>
gitlab_admin_pass = <your-gitlab-password>
### Which protocol should git connect to gitlab using? <ssh/https>
#gitlab_sync_connection_type = https

### If your gitlab instance requires client authentication,
### uncomment these parameters, and provide the appropriate paths
### If gitlab_client_auth_cert is provided, client authentication is switched on
#gitlab_client_auth_cert = /path/to/gitlab_client_auth_cert.pem
#gitlab_client_auth_key = /path/to/gitlab_client_auth_key.pem
# Max records to retrieve in a single API call to GitLab
#gitlab_api_max_page_size=50

[migrate]

### Instance source
source=gitlab

### If True, Add a Forgejo team for every possible gitlab group member access level
#add_empty_teams_to_organizations=False

### If True, Add all Forgejo organisation teams to the repository owned by their organization, not just those with current users
#add_empty_teams_to_repositories=False

### If an organization team exists matching the role of a user being imported:
### False: the original team will be renamed with suffix _old
### True: the users will be added to the existing team
### Notes:
###  1. that team (including existing users will gain repository access)
###  2. OWNER Role teams cannot be renamed out of the way (you'll get warning if there are existing users in an OWNER Role team for the Organization)
### use_existing_teams=False

### When creating collaborators, are teams permitted to utilise the Forgejo nearest neighbor permission?
#allow_fuzzy_teams=False

### When creating collaborators, are users permitted to utilise the Forgejo nearest neighbor permission?
#allow_fuzzy_users=False

### If True, allow the closest lower permission defined Forgejo team to be used in lieu (lower have precedence over higher)
#allow_fuzzy_auth_downgrade=False

### If True, allow the closest higher permission defined Forgejo team to be used in lieu (lower have precedence over higher)
#allow_fuzzy_auth_upgrade=False

### Define how the Organizations, Teams and Users are created (see comments in strategies files for examples)
# Pick one of [access_level,strict_access_level,no_teams,preserve_existing_teams,flatten_source_team_hierarchy]
#
# If you encounter a bug in a strategy, please let me know so it can be fixed for other people (ideally, send me a fix ;-) ).
#
# Note: I recommend that you create a user just for the migration process if using strategy: preserve_existing_teams
#access_mapping_strategy=access_level



[migrate.gitlab]

### If True, users found matching ^project_[0-9]{2}_bot_[a-zA-Z0-9]{32}$ or in list ignored_gitlab_system_users will NOT be imported, but generate a warning instead
#ignore_gitlab_system_users=False

### All exact matches on this list will not be imported (if ignore_gitlab_system_users=True)
#ignored_gitlab_system_users="GitLab-Admin-Bot,ghost,support-bot,alert-bot,GitLabDuo"
```

### Credits and fork information

This is a fork of [https://github.com/GEANT/gitlab-to-forgejo,](https://github.com/GEANT/gitlab-to-forgejo,) but the changes are now so substantial that it isn't mergeable upstream as a 'patch' any more.

Some of the key Changes:

*   ~I've re-added support for issues, milestones and labels, though don't use these myself.~
*   I've added support for gitlab client certificate authentication (for when the server is behind a proxy enforcing this)
*   I've added support for forgejo client certificate authentication (for when the server is behind a proxy enforcing this)
*   I've updated this script to use the new API for forgejo (2.0+).
*   I tried to make minimal changes initially, but in the end, I have refactored it to the point it is now a reusable more modular migration engine
*   Added support for user PGP and GPG key import, though don't use these myself.
*   **Added support for importing Organization Teams and Users to match GitLab Users and Gitlab Groups, assigning using Roles based on gitlab access level.**
*   **Added support for applying Collaboration entries for Repositories based on the Users' membership of Gitlab Group and or Project**
*   **Multiple strategies exist for migration of  Teams and Users (pick in config file). To add your own shouldn't be too taxing**
*   **Added support for User avatar migration**
*   Adding a different source to migrate from is now much easier, just implement your own MigrationSource class and swap from GitLabMigrationSource in migrate.py.

Note:

*   I have added warnings where users are found that I think are likely to be gitlab system users. They are imported anyway by default, but you're made aware. You can choose to filter out gitlab system users from the migration.
*   I have not yet re-added support for custom import of labels, milestones since this is handled inside the core Forgejo migration of a repository.
