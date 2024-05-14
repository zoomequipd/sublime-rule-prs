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

def get_commits_for_pull_request(pr_number):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_number}/commits'
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def get_file_contents(commit_sha, path):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}?ref={commit_sha}'
    response = requests.get(url, headers=headers)
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
        pr_number = pr['number']
        print(f"Processing PR #{pr_number}: {pr['title']}")
        commits = get_commits_for_pull_request(pr_number)

        for commit in commits:
            commit_sha = commit['sha']
            commit_url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/{commit_sha}'
            commit_data = requests.get(commit_url, headers=headers).json()
            files = commit_data['files']

            for file in files:
                if file['status'] == 'added' and file['filename'].startswith('detection-rules/'):
                    content = get_file_contents(commit_sha, file['filename'])
                    save_file(file['filename'], content)
                    new_files.add(os.path.basename(file['filename']))

    clean_output_folder(new_files)

if __name__ == '__main__':
    main()
