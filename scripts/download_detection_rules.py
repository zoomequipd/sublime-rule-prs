import base64
import os
import uuid
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import quote

import requests

# Common configuration
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
SUBLIME_API_TOKEN = os.getenv('SUBLIME_API_TOKEN')
REPO_OWNER = os.getenv('REPO_OWNER', 'sublime-security')
REPO_NAME = os.getenv('REPO_NAME', 'sublime-rules')
OUTPUT_FOLDER = os.getenv('OUTPUT_FOLDER', 'detection-rules')

# Script mode selection (default to 'standard' if not specified)
# Possible values: 'standard', 'test-rules'
SCRIPT_MODE = os.getenv('SCRIPT_MODE', 'standard')

# Standard mode configuration (original behavior)
# flag to control adding the author name into the tag
ADD_AUTHOR_TAG = os.getenv('ADD_AUTHOR_TAG', 'true').lower() == 'true'
AUTHOR_TAG_PREFIX = os.getenv('AUTHOR_TAG_PREFIX', 'pr_author_')

# flag to control of an additional tag is created which
# indicates the file status (modified vs added)
ADD_RULE_STATUS_TAG = os.getenv('ADD_RULE_STATUS_TAG', 'true').lower() == 'true'
RULE_STATUS_PREFIX = os.getenv('RULE_STATUS_PREFIX', 'rule_status_')

# flag to control if a reference is added which links to the PR in the repo
ADD_PR_REFERENCE = os.getenv('ADD_PR_REFERENCE', 'true').lower() == 'true'

# flag to modify the name of each rule to include the PR#
INCLUDE_PR_IN_NAME = os.getenv('INCLUDE_PR_IN_NAME', 'true').lower() == 'true'
# flag to enable creating a rule in the feed for net new rules
INCLUDE_ADDED = os.getenv('INCLUDE_ADDED', 'true').lower() == 'true'
# flag to enable creating a rule in the feed for updated (not net new) rules
INCLUDE_UPDATES = os.getenv('INCLUDE_UPDATES', 'true').lower() == 'true'
# flag to enable the removing rules from the platform when the PR is closed
DELETE_RULES_FROM_CLOSED_PRS = os.getenv('DELETE_RULES_FROM_CLOSED_PRS', 'true').lower() == 'true'
# variable that controls when the rules from a closed PR should be deleted
# this is in days
DELETE_RULES_FROM_CLOSED_PRS_DELAY = int(os.getenv('DELETE_RULES_FROM_CLOSED_PRS_DELAY', '3'))

# flag to add "created_from_open_prs" tag
CREATE_OPEN_PR_TAG = os.getenv('CREATE_OPEN_PR_TAG', 'true').lower() == 'true'
OPEN_PR_TAG = os.getenv('OPEN_PR_TAG', 'created_from_open_prs')

# Test-rules mode configuration

# flag to enable filtering PRs by organization membership
FILTER_BY_ORG_MEMBERSHIP = os.getenv('FILTER_BY_ORG_MEMBERSHIP', 'false').lower() == 'true'
# organization name to filter by
ORG_NAME = os.getenv('ORG_NAME', 'sublime-security')

# flag to enable including PRs with specific comments
INCLUDE_PRS_WITH_COMMENT = os.getenv('INCLUDE_PRS_WITH_COMMENT', 'false').lower() == 'true'
# comment text that triggers inclusion
COMMENT_TRIGGER = os.getenv('COMMENT_TRIGGER', '/update-test-rules')


# flag to skip files containing specific text
# this is due to test-rules not supporting specific functions
SKIP_FILES_WITH_TEXT = os.getenv('SKIP_FILES_WITH_TEXT', 'false').lower() == 'true'
# text to search for in files to skip
SKIP_TEXT = os.getenv('SKIP_TEXT', 'ml.link_analysis')

# flag to check if required actions have completed
# we should only include rules which have passed validation
CHECK_ACTION_COMPLETION = os.getenv('CHECK_ACTION_COMPLETION', 'true').lower() == 'true'
# name of the required workflow
REQUIRED_CHECK_NAME = os.getenv('REQUIRED_CHECK_NAME', 'Rule Tests and ID Updated')
# required conclusion of the workflow
REQUIRED_CHECK_CONCLUSION = os.getenv('REQUIRED_CHECK_CONCLUSION', 'success')

# Create output folder if it doesn't exist
if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

headers = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}


def is_user_in_org(username, org_name):
    """
    Check if a user is a member of a specific organization.

    Args:
        username (str): GitHub username
        org_name (str): Organization name

    Returns:
        bool: True if user is a member, False otherwise
    """
    url = f'https://api.github.com/orgs/{org_name}/members/{username}'
    response = requests.get(url, headers=headers)
    return response.status_code == 204


def has_trigger_comment(pr_number, org_name, trigger_comment):
    """
    Check if a PR has a comment with the trigger text from a member of the specified org.

    Args:
        pr_number (int): Pull request number
        org_name (str): Organization name to filter commenters
        trigger_comment (str): Comment text to look for

    Returns:
        bool: True if a matching comment is found, False otherwise
    """
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{pr_number}/comments'
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    comments = response.json()

    for comment in comments:
        # Check if comment contains the trigger and author is in the organization
        if trigger_comment in comment['body'] and is_user_in_org(comment['user']['login'], org_name):
            return True

    return False


def has_required_action_completed(pr_sha, action_name, required_status):
    """
    Check if a required GitHub Actions workflow has completed with the expected status for a PR.
    Uses the GitHub Checks API to poll for check results.

    Args:
        pr_sha (str): SHA of the PR head commit
        action_name (str): Name of the action/check to look for
        required_status (str): Required status (success, failure, etc.)

    Returns:
        bool: True if the action has completed with the required status, False otherwise
    """
    # Use the GitHub Checks API to get all check runs for this commit
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/{pr_sha}/check-runs'
    custom_headers = headers.copy()
    # Add the required Accept header for the Checks API
    custom_headers['Accept'] = 'application/vnd.github.v3+json'

    response = requests.get(url, headers=custom_headers)

    if response.status_code != 200:
        print(f"\tError checking action status: {response.status_code}")
        return False

    check_runs = response.json()

    if 'check_runs' not in check_runs or len(check_runs['check_runs']) == 0:
        print(f"\tNo check runs found for commit {pr_sha}")
        return False

    # Look for the specific action by name
    for check in check_runs['check_runs']:
        check_name = check['name']
        check_conclusion = check['conclusion']
        check_status = check['status']

        if action_name.lower() in check_name.lower():

            # Check if the action is complete
            if check_status != 'completed':
                print(f"\tCheck '{check_name}' is still in progress (status: {check_status})")
                return False

            # Check if the action has the required conclusion
            if check_conclusion == required_status:
                return True
            else:
                print(f"\tCheck '{check_name}' has conclusion '{check_conclusion}', expected '{required_status}'")
                return False

    print(f"\tNo check matching '{action_name}' found")
    return False

def contains_skip_text(content, skip_text):
    """
    Check if file content contains the text to skip.

    Args:
        content (str): File content
        skip_text (str): Text to search for

    Returns:
        bool: True if content contains the skip text, False otherwise
    """
    return skip_text in content


def generate_deterministic_uuid(seed_string):
    """
    Generate a deterministic UUID based on a seed string.
    This ensures the same input will always produce the same UUID.

    Args:
        seed_string (str): A string to use as a seed for UUID generation

    Returns:
        str: A UUID string in the format of XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
    """
    # Create a namespace UUID (using the DNS namespace as a standard practice)
    namespace = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

    # Create a UUID using the namespace and the seed string
    deterministic_uuid = uuid.uuid5(namespace, seed_string)

    return str(deterministic_uuid)


def add_id_to_yaml(content, filename):
    """
    Adds or replaces an ID field in the YAML content.
    Extracts the original ID if present.

    Args:
        content (str): The YAML content
        filename (str): The filename to use as seed for UUID generation

    Returns:
        tuple: (modified_content, original_id) - The modified YAML content with the UUID added/replaced
               and the original ID if found, otherwise None
    """
    # Use the filename directly as the seed for UUID generation
    # Generate a deterministic UUID based on the seed
    new_uuid = generate_deterministic_uuid(filename)
    original_id = None

    # Check if 'id:' already exists in the content
    if 'id:' in content:
        # Extract the original ID
        pattern = r'^\s*id:\s*([^\n]*)'
        match = re.search(pattern, content, flags=re.MULTILINE)
        if match:
            original_id = match.group(1).strip()
            if original_id.startswith('"') and original_id.endswith('"'):
                original_id = original_id[1:-1]  # Remove surrounding quotes
            elif original_id.startswith("'") and original_id.endswith("'"):
                original_id = original_id[1:-1]  # Remove surrounding quotes

        # Replace with the new ID
        modified_content = re.sub(pattern, f'id: \"{new_uuid}\"', content, flags=re.MULTILINE)
        return modified_content, original_id
    else:
        # If it doesn't exist, add it to the very end of the YAML file
        # Make sure we have a clean end to the file (no trailing whitespace)
        modified_content = content.rstrip()

        # Add a newline and the ID field
        modified_content += f"\nid: \"{new_uuid}\""

        return modified_content, original_id


def search_sublime_rule_feed(rule_name):
    # strip quotes for searching
    rule_name = rule_name.strip("\"\'")
    rule_name = quote(rule_name)
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
    per_page = 30  # 100 is the max allowed items per page by GitHub API
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
            # print(f"Found name line: {line}")
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
    # extract the current name
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
    """
    Handle closed PRs by deleting rules from closed PRs after a delay period.

    Returns:
        set: Set of rule IDs that were deleted
    """
    if not DELETE_RULES_FROM_CLOSED_PRS:
        return set()

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
            print(
                f"\tSkipping non-main branch PR #{closed_pr['number']}: {closed_pr['title']} -- dest branch: {closed_pr['base']['ref']}")
            continue

        # we only care about the delay if it's been merged
        if closed_pr['merged_at'] is not None:
            merged_at_time = datetime.strptime(closed_pr['merged_at'], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc)

            # if the PR has been merged, then we add this delay to allow the PR author to still get alerts
            if not merged_at_time <= datetime.now(tz=timezone.utc) - timedelta(days=DELETE_RULES_FROM_CLOSED_PRS_DELAY):
                time_remaining = (merged_at_time + timedelta(days=3)) - datetime.now(tz=timezone.utc)

                remaining_days = time_remaining.days
                remaining_hours, remaining_remainder = divmod(time_remaining.seconds, 3600)
                remaining_minutes, remaining_seconds = divmod(remaining_remainder, 60)

                print(
                    f"\tDELAY NOT MET: Skipping PR #{closed_pr['number']}: {closed_pr['title']}\n\tRemaining Time = {remaining_days} days, {remaining_hours} hours, {remaining_minutes} minutes, {remaining_seconds} seconds")
                continue

        # if it's past the variable, then delete it
        files = get_files_for_pull_request(pr_number)

        for file in files:
            print(f"\tStatus of {file['filename']}: {file['status']}")
            # get all the rules from the close PR
            if file['status'] in ['added', 'modified', 'changed'] and file['filename'].startswith(
                    'detection-rules/') and file['filename'].endswith('.yml'):
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
                        if CREATE_OPEN_PR_TAG and OPEN_PR_TAG in found_rule.get('tags'):
                            print(f"\tFound {OPEN_PR_TAG} tag match")

                            if ADD_AUTHOR_TAG and f"{AUTHOR_TAG_PREFIX}{closed_pr['user']['login']}" in found_rule.get(
                                    'tags'):
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
                            print(f"\t{OPEN_PR_TAG} not found in: ")
                            print(found_rule.get('tags'))
                    else:
                        print("\tRule not match not found: ")
                        print(f"\tFound Rule:    {found_rule.get('name')}")
                        print(f"\tEtracted Rule: {rule_name.strip('\'\"')}")

    print(f"Deleted {len(deleted_ids)} Rules from Closed PRs:")

    for deleted_id in deleted_ids:
        print(f"\t{deleted_id}")

    return deleted_ids


def handle_pr_rules(mode):
    """
    Process open PRs to create rules based on the specified mode.

    This function handles both standard mode and test-rules mode processing.
    In test-rules mode, it adds special fields required for test rules (og_id, testing_pr, testing_sha).

    Args:
        mode (str): Either 'standard' or 'test-rules'

    Returns:
        set: Set of filenames that were processed
    """
    # Display appropriate header based on mode
    if mode == 'standard':
        header = [
            ' _____                    ______      _ _   ______                           _       ',
            '|  _  |                   | ___ \\    | | |  | ___ \\                         | |      ',
            '| | | |_ __   ___ _ __    | |_/ /   _| | |  | |_/ /___  __ _ _   _  ___  ___| |_ ___ ',
            '| | | | \'_ \\ / _ \\ \'_ \\   |  __/ | | | | |  |    // _ \\/ _\' | | | |/ _ \\/ __| __/ __|',
            '\\ \\_/ / |_) |  __/ | | |  | |  | |_| | | |  | |\\ \\  __/ (_| | |_| |  __/\\__ \\ |_\\__ \\',
            ' \\___/| .__/ \\___|_| |_|  \\_|   \\__,_|_|_|  \\_| \\_\\___|\\__, |\\__,_|\\___||___/\\__|___/',
            '      | |                                                 | |                        ',
            '      |_|                                                 |_|                        ',
        ]
    else:  # test-rules mode
        header = [
            ' _____         _     ______      _          ',
            '|_   _|       | |    | ___ \\    | |         ',
            '  | | ___  ___| |_   | |_/ /   _| | ___  ___ ',
            '  | |/ _ \\/ __| __|  |    / | | | |/ _ \\/ __|',
            '  | |  __/\\__ \\ |_   | |\\ \\ |_| | |  __/\\__ \\',
            '  \\_/\\___||___/\\__|  \\_| \\_\\__,_|_|\\___||___/',
            '                                            ',
        ]

    for line in header:
        print(line)

    pull_requests = get_open_pull_requests()
    new_files = set()

    for pr in pull_requests:
        # Common checks for all modes
        if pr['draft']:
            print(f"Skipping draft PR #{pr['number']}: {pr['title']}")
            continue
        if pr['base']['ref'] != 'main':
            print(f"Skipping non-main branch PR #{pr['number']}: {pr['title']} -- dest branch: {pr['base']['ref']}")
            continue

        pr_number = pr['number']

        # Organization membership and comment trigger checks (for any mode if flags are set)
        process_pr = True
        if FILTER_BY_ORG_MEMBERSHIP:
            author_in_org = is_user_in_org(pr['user']['login'], ORG_NAME)
            has_comment = False

            if INCLUDE_PRS_WITH_COMMENT:
                has_comment = has_trigger_comment(pr['number'], ORG_NAME, COMMENT_TRIGGER)

            if not (author_in_org or has_comment):
                print(f"Skipping PR #{pr['number']}: Author not in {ORG_NAME} and no trigger comment found")
                process_pr = False

        if not process_pr:
            continue

        print(f"Processing PR #{pr_number}: {pr['title']}")

        # Get the latest commit SHA directly from the PR data
        latest_sha = pr['head']['sha']
        print(f"\tLatest commit SHA: {latest_sha}")

        # Check if required checks have completed (if flag is set)
        if CHECK_ACTION_COMPLETION:
            if not has_required_action_completed(latest_sha, REQUIRED_CHECK_NAME, REQUIRED_CHECK_CONCLUSION):
                print(
                    f"\tSkipping PR #{pr_number}: Required check '{REQUIRED_CHECK_NAME}' has not completed with conclusion '{REQUIRED_CHECK_CONCLUSION}'")
                continue

        files = get_files_for_pull_request(pr_number)

        # Process files in the PR
        for file in files:
            print(f"\tStatus of {file['filename']}: {file['status']}")
            process_file = False

            # Common file type and status check
            if file['status'] in ['added', 'modified', 'changed'] and file['filename'].startswith(
                    'detection-rules/') and file['filename'].endswith('.yml'):
                if file['status'] == "added" and INCLUDE_ADDED:
                    process_file = True
                elif file['status'] in ['modified', 'changed'] and INCLUDE_UPDATES:
                    process_file = True
                else:
                    print(
                        f"\tSkipping {file['status']} file: {file['filename']} in PR #{pr['number']} -- INCLUDE_UPDATES == {INCLUDE_UPDATES}, INCLUDE_ADDED == {INCLUDE_ADDED}")
            else:
                print(
                    f"\tSkipping {file['status']} file: {file['filename']} in PR #{pr['number']} -- unmanaged file status")

            # If file should be processed, get content and apply mode-specific logic
            if process_file:
                content = get_file_contents(file['contents_url'])

                # Skip files with specific text if flag is set
                if SKIP_FILES_WITH_TEXT and contains_skip_text(content, SKIP_TEXT):
                    print(f"\tSkipping file {file['filename']}: contains {SKIP_TEXT}")
                    continue

                # Process file (common for both modes)
                target_save_filename = f"{pr['number']}_{os.path.basename(file['filename'])}"

                # Get the modified content and original ID
                modified_content, original_id = add_id_to_yaml(content, target_save_filename)

                # Test-rules mode: add special fields
                if mode == 'test-rules':
                    # Store the original id
                    if original_id:
                        modified_content = modified_content.rstrip()
                        modified_content += f"\nog_id: \"{original_id}\""

                    # Add the PR number as testing_pr
                    modified_content = modified_content.rstrip()
                    modified_content += f"\ntesting_pr: {pr_number}"

                    # Add the commit SHA as testing_sha
                    modified_content = modified_content.rstrip()
                    modified_content += f"\ntesting_sha: {latest_sha}"

                # Common modifications based on flags
                if ADD_AUTHOR_TAG:
                    modified_content = add_block(modified_content, 'tags', f"{AUTHOR_TAG_PREFIX}{pr['user']['login']}")

                # Add open PR tag if flag is set
                if CREATE_OPEN_PR_TAG:
                    modified_content = add_block(modified_content, 'tags', OPEN_PR_TAG)

                if ADD_RULE_STATUS_TAG:
                    modified_content = add_block(modified_content, 'tags', f"{RULE_STATUS_PREFIX}{file['status']}")

                if ADD_PR_REFERENCE:
                    modified_content = add_block(modified_content, 'references', pr['html_url'])

                if INCLUDE_PR_IN_NAME:
                    modified_content = rename_rules(modified_content, pr)

                # Save the file
                save_file(target_save_filename, modified_content)
                new_files.add(target_save_filename)
                print(f"\tSaved: {target_save_filename}")

    # Clean up files no longer in open PRs
    clean_output_folder(new_files)
    return new_files


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

    # Determine which functions to run based on SCRIPT_MODE
    if SCRIPT_MODE == 'standard':
        print("Running in standard mode...")
        handle_pr_rules('standard')
        handle_closed_prs()

    elif SCRIPT_MODE == 'test-rules':
        print("Running in test-rules mode...")
        handle_pr_rules('test-rules')

    else:
        print(f"Error: Unknown SCRIPT_MODE '{SCRIPT_MODE}'. Valid options are 'standard' or 'test-rules'.")
        exit(1)
