
from dataclasses import asdict
import re


def diff_dataclasses(before, after) -> dict:
    before_dict = asdict(before)
    after_dict = asdict(after)

    diff = {}

    for key in before_dict.keys() | after_dict.keys():
        if before_dict.get(key) != after_dict.get(key):
            diff[key] = {
                "before": before_dict.get(key),
                "after": after_dict.get(key),
            }

    return diff



def name_clean(name):
    """Cleans a name for usage in Forgejo - names can be used as identifiers,
       so this is necessary for usernames, organization names, repo names, team names etc"""
    new_name = name.replace(" ", "_")
    new_name = re.sub(r"[^a-zA-Z0-9_\.-]", "-", new_name)

    if new_name.lower() == "plugins":
        return f"{new_name}-user"

    return new_name