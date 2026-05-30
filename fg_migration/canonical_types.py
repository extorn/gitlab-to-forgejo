
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import List

from fg_migration.utils import name_clean


@dataclass
class CanonicalUser:
    username: str

    def __init__(self, username:str):
        self.username = username

    def get_safe_username(self) -> str:
        return name_clean(self.username)

@dataclass
class CanonicalGpgKey:
    name:str
    armored_public_key: str
    armored_signature:str|None

    def __init__(self, name:str,armored_public_key:str, armored_signature:str):
        self.name = name
        self.armored_public_key = armored_public_key
        self.armored_signature = armored_signature

@dataclass
class CanonicalKey:
    name:str
    key: str

    def __init__(self, name:str,key:str):
        self.name = name
        self.key = key

@dataclass
class CanonicalSystemUser:
    source_system:str
    username: str
    full_name: str
    email: str
    gpg_keys:List[CanonicalGpgKey]
    keys:List[CanonicalKey]

    def __init__(self, source_system:str, username:str, gpg_keys:List[CanonicalGpgKey], keys:List[CanonicalKey], full_name:str, email:str):
        self.source_system = source_system
        self.full_name = full_name
        self.email = email
        self.username = username
        self.gpg_keys = gpg_keys
        self.keys = keys

    def get_safe_username(self) -> str:
        return name_clean(self.username)

@dataclass
class CanonicalOrganizations:
    source_type:str
    members:List[CanonicalOrganization]

    def __init__(self, source_type:str, members:List[CanonicalOrganization]):
        self.source_type = source_type
        self.members = members

@dataclass
class CanonicalOrganization:
    source_type:str
    username: str
    full_name:str
    description:str
    teams:List[CanonicalTeam]

    def __init__(self, source_type:str, username:str, full_name:str, description:str, teams:List[CanonicalTeam]):
        self.source_type = source_type
        self.full_name = full_name
        self.description = description
        self.username = username
        self.teams = teams

    def get_safe_username(self) -> str:
        return name_clean(self.username)

@dataclass
class CanonicalTeam:
    #username: str
    source_access_level:str
    users:List[CanonicalUser]

    def __init__(self, username:str, source_access_level:str, users:List[CanonicalUser]):
        self.username = username
        self.source_access_level = source_access_level
        self.users = users

    #def get_safe_username(self) -> str:
    #    return name_clean(self.username)

@dataclass
class CanonicalRepoAccessor:
    username:str
    access_level:str

    def get_safe_username(self) -> str:
        return name_clean(self.username)

@dataclass
class CanonicalRepoAccessors:
    members:List[CanonicalRepoAccessor]
    source_system:str
    source_type:str
    def __init__(self, source_system:str, members=List[CanonicalRepoAccessor], source_type="Users"):
        self.members = members
        self.source_type = source_type
        self.source_system = source_system

    @staticmethod
    def get_grouped_by_access_level(members:List[CanonicalRepoAccessor]) -> dict[str,set[CanonicalRepoAccessor]]:
        grouped_by_access_level : dict[str,set[CanonicalRepoAccessor]] = defaultdict(set)
        for member in members:
            grouped_by_access_level[member.access_level].add(member)
        return grouped_by_access_level
    


@dataclass
class CanonicalRepo:

    is_individual:bool # Owned by a user? (else an organization)
    name:str
    description:str
    owner_name: str
    clone_url:str
    is_private:bool
    auth_password:str
    auth_username:str
    auth_token:str
    source_system:str
    source_id:str
    source_type: str # what is this called in the source system

    def __init__(self, 
                 source_system:str,
                 is_individual:bool,name:str,owner_name:str,clone_url:str,is_private:bool,description:str,
                 source_id:str,
                 auth_username:str,auth_password:str,auth_token:str,
                 source_type:str="Repository"):
        self.is_individual = is_individual
        self.is_private = is_private
        self.name = name
        self.description = description
        self.auth_username=auth_username,
        self.auth_password=auth_password,
        self.auth_token=auth_token
        self.owner_name = owner_name
        self.source_system = source_system
        self.source_type = source_type
        self.source_id = source_id
        self.clone_url = clone_url

    def get_safe_name(self) -> str:
        return name_clean(self.name)
    
    def get_safe_owner_name(self) -> str:
        return name_clean(self.owner_name)

class CanonicalRepositoryRole(Enum):
    OWNER = "Owner",
    MAINTAINER = "Maintainer",
    DEVELOPER = "Developer",
    REPORTER = "Reporter",
    GUEST = "Guest"

class MigrationSource(ABC):
    @abstractmethod
    def getSourceSystemName(self) -> str:
        pass

    @abstractmethod
    def listRepos(self) -> List[CanonicalRepo]:
        pass

    @abstractmethod
    def list_organizations(self) -> CanonicalOrganizations:
        pass

    @abstractmethod
    def list_repository_accessors(self, repo:CanonicalRepo) -> CanonicalRepoAccessors:
        pass

    @abstractmethod
    def list_system_users(self) -> List[CanonicalSystemUser]:
        pass

    @abstractmethod
    def get_repository_role(self, source_access_level:str) -> CanonicalRepositoryRole | str:
        pass

    @abstractmethod
    def get_nearest_repository_role(self, source_access_level:str,
                                 allow_downgrade:bool,
                                 allow_upgrade:bool) -> CanonicalRepositoryRole | None:
        pass