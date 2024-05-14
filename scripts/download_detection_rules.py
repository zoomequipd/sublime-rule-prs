import os
import base64
import requests

GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
REPO_OWNER = 'sublime-security'
REPO_NAME = 'sublime-rules'
OUTPUT_FOLDER = 'detection-rules'

if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

headers = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

def get_open_pull_requests():
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls'
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


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


def main():
    pull_requests = get_open_pull_requests()

    new_files = set()

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
                save_file(file['filename'], content)
                new_files.add(os.path.basename(file['filename']))
                print(f"Saved: {file['filename']}")

    clean_output_folder(new_files)


if __name__ == '__main__':
    main()
