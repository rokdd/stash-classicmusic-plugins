"""Creates the performer Ludwig van Beethoven (alias Beethoven, custom field composer=yes)
in a Stash instance, then runs Tag Improvements' "Sync composer tags" task, which creates
the Composers parent tag and Beethoven's tag under it. Standard library only.
Usage: python3 example_composer.py [http://192.168.155.23:9999]"""
import json, sys, urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://192.168.155.23:9999").rstrip("/")

def gql(query, variables=None):
    req = urllib.request.Request(BASE + "/graphql", json.dumps({"query": query, "variables": variables or {}}).encode(),
                                 {"Content-Type": "application/json"})
    data = json.load(urllib.request.urlopen(req, timeout=60))
    if data.get("errors"):
        raise SystemExit(json.dumps(data["errors"], indent=1))
    return data["data"]

found = gql('query($f: PerformerFilterType){ findPerformers(performer_filter: $f){ performers{ id name } } }',
            {"f": {"name": {"value": "Ludwig van Beethoven", "modifier": "EQUALS"}}})["findPerformers"]["performers"]
if found:
    pid = found[0]["id"]
    gql('mutation($i: PerformerUpdateInput!){ performerUpdate(input: $i){ id } }',
        {"i": {"id": pid, "custom_fields": {"partial": {"composer": "yes"}}}})
    print("Performer exists, marked as composer:", pid)
else:
    pid = gql('mutation($i: PerformerCreateInput!){ performerCreate(input: $i){ id } }',
              {"i": {"name": "Ludwig van Beethoven", "alias_list": ["Beethoven"],
                     "details": "German composer and pianist (1770–1827).",
                     "birthdate": "1770-12-17", "death_date": "1827-03-26", "gender": "MALE",
                     "custom_fields": {"full": {"composer": "yes"}}}})["performerCreate"]["id"]
    print("Created performer:", pid)

# the plugin id is the plugin's .yml file name (tagTree.yml → tagTree)
print(gql('mutation{ runPluginTask(plugin_id: "tagTree", task_name: "Sync composer tags") }'))
print("Check Settings → Tasks (log) and Tags → Composers → Ludwig van Beethoven.")
