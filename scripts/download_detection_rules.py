import os
import base64
import requests

GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
REPO_OWNER = 'sublime-security'
REPO_NAME = 'sublime-rules'
OUTPUT_FOLDER = 'detection-rules'
ADD_AUTHOR_TAG = True
AUTHOR_TAG_PREFIX = "pr_author_"

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

headers = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

def get_open_pull_requests():
    pull_requests = []
    page = 1
    per_page = 30  # 100 is the max allowed items per page by GitHub API
    
    while True:
        url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls'
        params = {'page': page, 'per_page': per_page}
        print(f"fetching page {page} of Pull Requests")
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
            print(f"fetched page {page} of Pull Requests, no more pages")
            print(f"Total PRs: {len(pull_requests)}")
            break  # No more pages, exit loop
        
        print(f"fetched page {page} of Pull Requests, moving to {page + 1}")
        print(f"PRs on page {page}: {len(response.json())}")
        print(f"PRs found so far: {len(pull_requests)}")
        page += 1  # Move to the next page
        

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


def add_author_tag(yaml_string, author):
    if "tags:" in yaml_string:
        # find the tags block
        start_tags = yaml_string.find("tags:")

        #  the end of the 'tags' block by locating the next section or end of the string
        end_tags = start_tags
        
        while True:
            next_line_start = yaml_string.find("\n", end_tags + 1)
            ## if there isn't a new line found, we've hit the end of the file
            ## or if the next line doesn't start with a space (which indicates it's still within the tag section)
            if next_line_start == -1 or not yaml_string[next_line_start + 1].isspace():
                if next_line_start != -1:
                    end_tags = next_line_start 
                else:
                    len(yaml_string)
                break
            end_tags = next_line_start

        # get the original tags block
        tags_block = yaml_string[start_tags:end_tags].strip()

        existing_tags = []
        # Split the tags into a list
        for line in tags_block.splitlines():
            # within the tags_block is the tag section header, skip that one
            if line.strip() == "tags:":
                continue
            line = line.strip()
            line = line.lstrip('-')
            # strip leading spaces after the - too
            line = line.strip()
            
            existing_tags.append(line)
        # add the author tag to the existing tags array
        existing_tags.append(f"{AUTHOR_TAG_PREFIX}{author}")

        new_tags_string = "tags:"
        for tag in existing_tags:
            new_tags_string += f"\n  - {tag}"
        # replace the old with the new
        modified_yaml_string = yaml_string.replace(tags_block, new_tags_string)
    else:
        # just add it at the end
        new_tags_block = f"tags:\n  - {AUTHOR_TAG_PREFIX}{author}"
        modified_yaml_string = yaml_string.strip() + "\n" + new_tags_block

    return modified_yaml_string


def main():
    pull_requests = get_open_pull_requests()

    new_files = set()

    if ADD_AUTHOR_TAG:
        print("Injecting PR Author as a tag")
    for pr in pull_requests:
        if pr['draft']:
            print(f"Skipping draft PR #{pr['number']}: {pr['title']}")
            continue

        pr_number = pr['number']
        print(f"Processing PR #{pr_number}: {pr['title']}")
        files = get_files_for_pull_request(pr_number)

        for file in files:
            if file['status'] == 'added' and file['filename'].startswith('detection-rules/'):
                content = get_file_contents(file['contents_url'])
                if ADD_AUTHOR_TAG:
                    # inject the tags for test rules into the contents
                    
                    content = add_author_tag(content, pr['user']['login'])
                save_file(file['filename'], content)
                new_files.add(os.path.basename(file['filename']))
                print(f"Saved: {file['filename']}")

    clean_output_folder(new_files)


if __name__ == '__main__':
    main()
