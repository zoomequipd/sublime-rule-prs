import os
import base64
import requests
from datetime import datetime, timedelta, timezone

GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
SUBLIME_API_TOKEN = os.getenv('SUBLIME_API_TOKEN')
REPO_OWNER = 'sublime-security'
REPO_NAME = 'sublime-rules'
OUTPUT_FOLDER = 'detection-rules'
# flag to control adding the author name into the tag, allows for triage rules to be built on a per author basis
# without having to modify the author value of the rule
ADD_AUTHOR_TAG = True
AUTHOR_TAG_PREFIX = "pr_author_"

# flag to control of an additional tag is created which 
# indicates the file status (modified vs added)
ADD_RULE_STATUS_TAG = True
RULE_STATUS_PREFIX = "rule_status_"

# flag to control if a reference is added which links to the PR in the repo
ADD_PR_REFERENCE = True

# flag to modify the name of each rule to include the PR#
INCLUDE_PR_IN_NAME = True
# flag to enable creating a rule in the feed for net new rules
INCLUDE_ADDED = True
# flag to enable creating a rule in the feed for updated (not net new) rules
INCLUDE_UPDATES = True
# flag to enable the removing rules from the platform when the PR is closed
DELETE_RULES_FROM_CLOSED_PRS = True
# variable that controls when the rules from a closed PR should be deleted
# this is in days
DELETE_RULES_FROM_CLOSED_PRS_DELAY = 3

# flag to add "created_from_open_prs" tag
CREATE_OPEN_PR_TAG = True
OPEN_PR_TAG = "created_from_open_prs"

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

headers = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}


def search_sublime_rule_feed(rule_name):
    # strip quotes for searching
    rule_name = rule_name.strip("\"\'")
    rule_name = requests.utils.quote(rule_name)
    # print(f"Searching Sublime for rules with name: {rule_name}")
    url = f"https://platform.sublime.security/v0/rules?limit=50&offset=0&search={rule_name}"
    
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {SUBLIME_API_TOKEN}"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status() 
    except requests.exceptions.HTTPError as err:
        print(f"HTTP error occurred: {err}")
        # the calling function handles None
        return None
    except requests.exceptions.ConnectionError as err:
        print(f"Connection error occurred: {err}")
        # the calling function handles None
        return None
    else:
        print(f"\tSearch Feed Response Code: {response.status_code}")
        response = response.json()
        print(f"\tSearch Feed Found Count: {response['count']}")
        return response


def sublime_delete_rule(rule_id):

    url = f"https://platform.sublime.security/v0/rules/{rule_id}"
    
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {SUBLIME_API_TOKEN}"
    }
    response = requests.delete(url, headers=headers)

    print(f"\tDelete Rule Response Code: {response.status_code}")

    return response.ok


def get_closed_pull_requests():
    closed_pull_requests = []
    page = 1
    per_page = 30 # 100 is the max allowed items per page by GitHub API
    max_closed = 60
    
    while len(closed_pull_requests) <= max_closed:
        if len(closed_pull_requests) >= max_closed:
            print("hit max closed prs length")
            break
        
        url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls'
        params = {'page': page, 'per_page': per_page, 'state': 'closed', 'sort': 'updated', 'direction': 'desc'}
        print(f"Fetching page {page} of CLOSED Pull Requests")
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        # Extend the list with the pull requests from the current page
        closed_pull_requests.extend(response.json())
        
        # Check if there is a 'Link' header and whether it contains 'rel="next"'
        if 'Link' in response.headers:
            links = response.headers['Link'].split(', ')
            has_next = any('rel="next"' in link for link in links)
        else:
            has_next = False

        if not has_next:
            print(f"Fetched page {page} of Pull Requests")
            print(f"PRs on page {page}: {len(response.json())}")
            break  # No more pages, exit loop
        
        print(f"Fetched page {page} of CLOSED Pull Requests")
        print(f"CLOSED PRs on page {page}: {len(response.json())}")
        print(f"CLOSED PRs found so far: {len(closed_pull_requests)}")
        print(f"Moving to page {page + 1}")
        page += 1  # Move to the next page  

    print(f"Total CLOSED PRs: {len(closed_pull_requests)}")
    return closed_pull_requests


def get_open_pull_requests():
    pull_requests = []
    page = 1
    per_page = 30  # 100 is the max allowed items per page by GitHub API
    
    while True:
        url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls'
        params = {'page': page, 'per_page': per_page, 'sort': 'updated', 'direction': 'desc'}
        print(f"Fetching page {page} of Pull Requests")
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        # Extend the list with the pull requests from the current page
        pull_requests.extend(response.json())
        
        # Check if there is a 'Link' header and whether it contains 'rel="next"'
        if 'Link' in response.headers:
            links = response.headers['Link'].split(', ')
            has_next = any('rel="next"' in link for link in links)
        else:
            has_next = False

        if not has_next:
            print(f"Fetched page {page} of Pull Requests")
            print(f"PRs on page {page}: {len(response.json())}")
            break  # No more pages, exit loop
        
        print(f"Fetched page {page} of Pull Requests")
        print(f"PRs on page {page}: {len(response.json())}")
        print(f"PRs found so far: {len(pull_requests)}")
        print(f"Moving to page {page + 1}")
        page += 1  # Move to the next page  

    print(f"Total PRs: {len(pull_requests)}")
    return pull_requests


def get_files_for_pull_request(pr_number):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_number}/files'
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def get_file_contents(contents_url):
    response = requests.get(contents_url, headers=headers)
    response.raise_for_status()
    content = response.json()['content']
    return base64.b64decode(content).decode('utf-8')


def save_file(path, content):
    file_path = os.path.join(OUTPUT_FOLDER, os.path.basename(path))
    with open(file_path, 'w') as file:
        file.write(content)


def clean_output_folder(valid_files):
    for filename in os.listdir(OUTPUT_FOLDER):
        file_path = os.path.join(OUTPUT_FOLDER, filename)
        if filename not in valid_files:
            print(f"Removing file: {filename}")
            os.remove(file_path)

def extract_rule_name(content):
    current_name = ""
    lines = content.split('\n')
    for line in lines:
        if 'name:' in line:
            #print(f"Found name line: {line}")
            # replace the quotes and spaces to create a clean filename
            current_name = line.replace('name: ', '').strip()
            break
    
    return current_name


def prepend_pr_details(rule_name, pr):
    # maintain the original quoting around the name
    if rule_name.startswith('"') and rule_name.endswith('"'):
        new_name = f"\"PR# {pr['number']} - {rule_name.strip("\" ")}\""
    elif rule_name.startswith('\'') and rule_name.endswith('\''):
        new_name = f"\'PR# {pr['number']} - {rule_name.strip("\' ")}\'"
    else:
        new_name = f"PR# {pr['number']} - {rule_name}"
    # replace it in the content
    # print(f"New Name: {new_name}")
    # print(f"Old Name: {rule_name}")

    return new_name

def rename_rules(content, pr):
    #extract the current name
    current_name = extract_rule_name(content)
    # build out the new name to inject the PR number
    new_name = prepend_pr_details(current_name, pr)
    
    content = content.replace(current_name, new_name)
    return content

def add_block(yaml_string, block_name, value):
    # throw an error if the block name isn't known
    if block_name not in ['tags', 'references', 'tags:', 'references:']:
        raise ValueError(f'Block Name: {block_name} is unsupported')
    # if it doesn't have the : needed, add it.

    if not block_name.endswith(':'):
        block_name = f"{block_name}:"
        
    if block_name in yaml_string:
        # find the tags block
        start_block = yaml_string.find(block_name)

        #  the end of the block by locating the next section or end of the string
        end_block = start_block
        
        while True:
            next_line_start = yaml_string.find("\n", end_block + 1)
            ## if there isn't a new line found, we've hit the end of the file
            ## or if the next line doesn't start with a space (which indicates it's still within the tag section)
            if next_line_start == -1 or not yaml_string[next_line_start + 1].isspace():
                if next_line_start != -1:
                    end_block = next_line_start 
                else:
                    len(yaml_string)
                break
            end_block = next_line_start

        # get the original block
        block = yaml_string[start_block:end_block].strip()

        existing_block_entries = []
        # Split the tags into a list
        for line in block.splitlines():
            # within the tags_block is the tag section header, skip that one
            if line.strip() == block_name:
                continue
            line = line.strip()
            line = line.lstrip('-')
            # strip leading spaces after the - too
            line = line.strip()
            
            existing_block_entries.append(line)
        # add the author tag to the existing tags array
        existing_block_entries.append(f"{value}")


        new_block_string = block_name
        for entry in existing_block_entries:
            new_block_string += f"\n  - {entry}"
        # replace the old with the new
        modified_yaml_string = yaml_string.replace(block, new_block_string)
    else:
        # just add it at the end
        new_block_string = f"{block_name}\n  - {value}"
        # add additional tag to help filter down to the right rule id later
        modified_yaml_string = yaml_string.strip() + "\n" + new_block_string

    return modified_yaml_string


def handle_closed_prs():
    if not DELETE_RULES_FROM_CLOSED_PRS:
        return
        
    closed_pr_header = [
        ' _____ _                    _   ______      _ _   ______                           _       ',
        '/  __ \\ |                  | |  | ___ \\    | | |  | ___ \\                         | |      ',
        '| /  \\/ | ___  ___  ___  __| |  | |_/ /   _| | |  | |_/ /___  __ _ _   _  ___  ___| |_ ___ ',
        '| |   | |/ _ \\/ __|/ _ \\/ _\' |  |  __/ | | | | |  |    // _ \\/ _\' | | | |/ _ \\/ __| __/ __|',
        '| \\__/\\ | (_) \\__ \\  __/ (_| |  | |  | |_| | | |  | |\\ \\  __/ (_| | |_| |  __/\\__ \\ |_\\__ \\',
        ' \\____/_|\\___/|___/\\___|\\__,_|  \\_|   \\__,_|_|_|  \\_| \\_\\___|\\__, |\\__,_|\\___||___/\\__|___/',
        '                                                                | |                        ',
        '                                                                |_|                        ',
    ]
    
    for line in closed_pr_header:
        print(line)
        
    deleted_ids = set()
    closed_pull_requests = get_closed_pull_requests()
    
    for closed_pr in closed_pull_requests:
        pr_number = closed_pr['number']
        print(f"Processing CLOSED PR #{pr_number}: {closed_pr['title']}")

        if closed_pr['base']['ref'] != "main":
            print(f"\tSkipping non-main branch PR #{closed_pr['number']}: {closed_pr['title']} -- dest branch: {closed_pr['base']['ref']}")

        # we only care about the delay if it's been merged
        if closed_pr['merged_at'] is not None:
            merged_at_time = datetime.strptime(closed_pr['merged_at'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
      
            # if the PR has been merged, then we add this delay to allow the PR author to still get alerts
            if not merged_at_time <= datetime.now(tz=timezone.utc) - timedelta(days=DELETE_RULES_FROM_CLOSED_PRS_DELAY):
                time_remaining = (merged_at_time + timedelta(days=3)) - datetime.now(tz=timezone.utc)
                
                remaining_days = time_remaining.days
                remaining_hours, remaining_remainder = divmod(time_remaining.seconds, 3600)
                remaining_minutes, remaining_seconds = divmod(remaining_remainder, 60)
            
                print(f"\tDELAY NOT MET: Skipping PR #{closed_pr['number']}: {closed_pr['title']}\n\tRemaining Time = {remaining_days} days, {remaining_hours} hours, {remaining_minutes} minutes, {remaining_seconds} seconds")
                continue
        
        # if it's past the variable, then delete it
        files = get_files_for_pull_request(pr_number)

        for file in files:
            print(f"\tStatus of {file['filename']}: {file['status']}")
            # get all the rules from the close PR
            if file['status'] in ['added', 'modified', 'changed'] and file['filename'].startswith('detection-rules/') and file['filename'].endswith('.yml'):
                # get their contents to extract the rule name for searching
                content = get_file_contents(file['contents_url'])
                # get the rule name
                rule_name = extract_rule_name(content)
                
                # if we are including the PR in the rule name (this helps us make sure we're finding the right one)
                # then we need to prepend it here, because it own't actually be in the name of the rule in the offiical feed
                if INCLUDE_PR_IN_NAME and not rule_name.startswith(f"PR#{pr_number} - "):
                    rule_name = prepend_pr_details(rule_name, closed_pr)
                
                # Finally search for the rule name in the SUBLIME_API
                found_rules = search_sublime_rule_feed(rule_name)
                if found_rules is None:
                    print(f"\tError Finding Rules in Platform for PR#{pr_number} - {rule_name}")
                    continue
                print(f"\tFound {found_rules['count']} matching the rule name")
                # it's possible we have more than one rule, if they match, delete them all
                for found_rule in found_rules.get('rules', []):
                    # make sure we're dealing with an exact match of the rule we expect
                    # found_rule won't have quotes around it, because it's taken from the json of the rule
                    if found_rule.get('name') == rule_name.strip('\'\"'):
                        print("\tFound Rule Name Match")
                        if CREATE_OPEN_PR_TAG and 'created_from_open_prs' in found_rule.get('tags'):
                            print("\tFound OPEN_PR tag match")

                            if ADD_AUTHOR_TAG and f"{AUTHOR_TAG_PREFIX}{closed_pr['user']['login']}" in found_rule.get('tags'):
                                print("\tFound author tag match")
                                print(f"\tFound Matching Rule to delete:  {found_rule['id']}")
                                # go delete that rule
                                deleted = sublime_delete_rule(found_rule['id'])
                                if deleted:
                                    print(f"\tDELETED Matching Rule:  {found_rule['id']}")
                                    deleted_ids.add(found_rule['id'])
                                else:
                                    print(f"\tERROR DELETING Matching Rule:  {found_rule['id']}")
                            else:
                                print(f"{AUTHOR_TAG_PREFIX}{closed_pr['user']['login']} not found in: ")
                                print(found_rule.get('tags'))
                        
                        else:
                            print("\tcreated_from_open_prs not found in: ")
                            print(found_rule.get('tags'))
                    else:
                        print("\tRule not match not found: ")
                        print(f"\tFound Rule:    {found_rule.get('name')}")
                        print(f"\tEtracted Rule: {rule_name.strip('\'\"')}")

    
    print(f"Deleted {len(deleted_ids)} Rules from Closed PRs:")
    
    for deleted_id in deleted_ids:
        print(f"\t{deleted_id}")
        
    return deleted_ids

def handle_open_prs():
    open_prs_header = [
        ' _____                    ______      _ _   ______                           _       ',
        '|  _  |                   | ___ \\    | | |  | ___ \\                         | |      ',
        '| | | |_ __   ___ _ __    | |_/ /   _| | |  | |_/ /___  __ _ _   _  ___  ___| |_ ___ ',
        '| | | | \'_ \\ / _ \\ \'_ \\   |  __/ | | | | |  |    // _ \\/ _\' | | | |/ _ \\/ __| __/ __|',
        '\\ \\_/ / |_) |  __/ | | |  | |  | |_| | | |  | |\\ \\  __/ (_| | |_| |  __/\\__ \\ |_\\__ \\',
        ' \\___/| .__/ \\___|_| |_|  \\_|   \\__,_|_|_|  \\_| \\_\\___|\\__, |\\__,_|\\___||___/\\__|___/',
        '      | |                                                 | |                        ',
        '      |_|                                                 |_|                        ',
    ]
    
    for line in open_prs_header:
        print(line)

        
    pull_requests = get_open_pull_requests()

    new_files = set()

    for pr in pull_requests:
        if pr['draft']:
            print(f"Skipping draft PR #{pr['number']}: {pr['title']}")
            continue
        if pr['base']['ref'] != 'main':
            print(f"Skipping non-main branch PR #{pr['number']}: {pr['title']} -- dest branch: {pr['base']['ref']}")
            continue

        pr_number = pr['number']
        print(f"Processing PR #{pr_number}: {pr['title']}")
        files = get_files_for_pull_request(pr_number)

        # loop through each file in the PR and see if we should include it in this feed
        for file in files:
            
            print(f"\tStatus of {file['filename']}: {file['status']}")
            process_file = False
            # has to be added, modified, or changed, within the detection-rules and a yml
            if file['status'] in ['added', 'modified', 'changed'] and file['filename'].startswith('detection-rules/') and file['filename'].endswith('.yml'):
                
                if file['status'] == "added" and INCLUDE_ADDED:
                    # if including net new rules is enabled, we'll process this file
                    process_file = True
                elif file['status'] in ['modified', 'changed'] and INCLUDE_UPDATES:
                    # if including modified rules rules is enabled, we'll process this file
                    process_file = True
                else:
                    print(f"\tSkipping {file['status']} file: {file['filename']} in PR #{pr['number']} -- INCLUDE_UPDATES == {INCLUDE_UPDATES}, INCLUDE_ADDED == {INCLUDE_ADDED}")
            else:
                print(f"\tSkipping {file['status']} file: {file['filename']} in PR #{pr['number']} -- unmanaged file status")
            
            # if we can process this file
            if process_file:
                # go get it
                content = get_file_contents(file['contents_url'])
                
                # check the flags to modify the file
                if ADD_AUTHOR_TAG:
                    # inject the tags for test rules into the contents
                    content = add_block(content, 'tags', f"{AUTHOR_TAG_PREFIX}{pr['user']['login']}")
                
                if CREATE_OPEN_PR_TAG:
                    content = add_block(content, 'tags', f"{OPEN_PR_TAG}")
                
                if ADD_RULE_STATUS_TAG:
                    content = add_block(content, 'tags', f"{RULE_STATUS_PREFIX}{file['status']}")
                    
                if ADD_PR_REFERENCE:
                    content = add_block(content, 'references', pr['html_url'])
                    
                if INCLUDE_PR_IN_NAME:
                    content = rename_rules(content, pr)

                
                
                # finally save it
                # include the pr number in the filename to avoid duplicates
                # use os.path.basename to drop the folder of the file, save_file uses OUTPUT_FOLDER anyway.
                target_save_filename = f"{pr['number']}_{os.path.basename(file['filename'])}"
                save_file(target_save_filename, content)
                new_files.add(target_save_filename)
                print(f"\tSaved: {target_save_filename}")
            
    clean_output_folder(new_files)


if __name__ == '__main__':

    sublime_header = [
        ' ______     __  __     ______     __         __     __    __     ______    ',
        '/\\  ___\\   /\\ \\ /\\ \\   /\\  == \\   /\\ \\       /\\ \\   /\\ "-./  \\   /\\  ___\\   ',
        '\\ \\___  \\  \\ \\ \\_\\ \\  \\ \\  __<   \\ \\ \\____  \\ \\ \\  \\ \\ \\-./\\ \\  \\ \\  __\\   ',
        ' \\/\\_____\\  \\ \\_____\\  \\ \\_____\\  \\ \\_____\\  \\ \\_\\  \\ \\_\\ \\ \\_\\  \\ \\_____\\ ',
        '  \\/_____/   \\/_____/   \\/_____/   \\/_____/   \\/_/   \\/_/  \\/_/   \\/_____/ ',
        '                                                                           ',
    ]
    
    for line in sublime_header:
        print(line)

    
    handle_open_prs()
    handle_closed_prs()
