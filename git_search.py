import requests, getpass, csv
from multiprocessing import Pool

output_dir = ""
github_url = ""

def new_github_session(api_token=None):
    if api_token is None:
        api_token = getpass.getpass("API Token:")
    headers = {
        "Authorization":f'token {api_token}'
    }
    session = requests.session()
    session.headers = headers
    return session

def get_repositories(session, github_api):
    repos_resp = session.get(f'{github_api}/repositories')
    repos = repos_resp.json()
    more = True
    while more:
        if 'next' in repos_resp.links.keys(): 
            repo_url = repos_resp.links['next']['url']
            repos_resp = session.get(repo_url)
            repos.extend(repos_resp.json())
        else:
            print("Retrieved all repos available")
            more = False
            continue
    return repos

def github_code_search(output_dir, search_str, github_url=github_url, api_token=None, context_padding=40):
    # logical or syntax not supported for searching... https://github.com/isaacs/github/issues/660
    if api_token is None:
        api_token = getpass.getpass("API Token:")
    if output_dir[-1:] == "\\":
        output_dir = output_dir[-1:]
    file_path = f'{output_dir}\\{search_str}_search.csv'
    github_api = f'{github_url}/api/v3'
    # do this to get partial string and not the whole blob
    text_match_header = {"Accept":"application/vnd.github.v3.text-match+json"}
    assignment_operators = ["=",":"]
    session = new_github_session(api_token=api_token)
    endpoints = session.get(github_api).json()
    code_search = endpoints['code_search_url'].split("?")[0]
    # this will only return 100, need to iterate
    # TODO: fix individual repo handling...
    repos = get_repositories(session, github_api)
    with open(file_path, 'w', newline='') as csvfile:
        fieldnames = [
            'repo',
            'owner',
            'owner_dn',
            'members',
            'latest_commit',
            'filename',
            'latest_file_commit',
            'var_assignment',
            'fragment',
            'all_results_for_repo'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for repo in repos:
            more = True
            items = []
            repo_name = repo['full_name']
            commits_url = repo['commits_url'].split("{")[0]
            commit_resp = session.get(commits_url)
            # should come back with a 409 if no commits
            if commit_resp.ok:
                latest_commit = commit_resp.json()
                latest_commit_date = latest_commit[0]['commit']['committer']['date']
                resp = session.get(f'{code_search}?q={search_str}+in:file+repo:{repo_name}&per_page=100',headers=text_match_header)
                # this is to handle marking if more than 1000 results for the repo, can't all be returned
                # it's capped at 1000 for some reason
                if 'last' in resp.links.keys():
                    last_url = resp.links['last']['url']
                    params = last_url.split('&')
                    if params[1] == 'per_page=100' and params[2] == 'page=10':
                        all_results = False
                    else:
                        all_results = True
                else:
                    all_results = True
                if 'items' in resp.json().keys():
                    items = resp.json()['items']
                else:
                    continue
                while more:
                    if 'next' in resp.links.keys():
                        result_url = resp.links['next']['url']
                        resp = session.get(result_url, headers=text_match_header)
                        items.extend(resp.json()['items'])
                    else:
                        print(f'Retrieved results for {repo_name}')
                        more = False    
                        continue
                if len(items) > 0:
                    for i in items:
                        path = i['path']
                        # could get the blob, but encoding and more than needed
                        start = i['text_matches'][0]['matches'][0]['indices'][0]
                        end = i['text_matches'][0]['matches'][0]['indices'][1]
                        s_index = ((start-(context_padding//2)) if start >= (context_padding//2) else 0)
                        fragment = i['text_matches'][0]['fragment'].replace("\n",'')
                        e_index = ((end+(context_padding//2)) if end <= (len(fragment)-(context_padding//2)) else len(fragment))
                        var_assign = (True if any(assign_op in fragment[end:(end+3)] for assign_op in assignment_operators) else False)
                        context = fragment[s_index:e_index]
                        # commit sha can be web scraped, but ill advised
                        # get the last commit to touch that file
                        file_commit_str = f'{commits_url}?path={path}&page=1&per_page=1'
                        latest_file_commit = session.get(file_commit_str).json()
                        if len(latest_file_commit) > 0:
                            latest_file_commit_date = latest_file_commit[0]['commit']['committer']['date']
                        else:
                            latest_file_commit_date = 'None'
                        if repo['owner']['type'] != 'User':
                            dn = "github user"
                            if repo['owner']['type'] == 'Organization':
                                org_name = repo['owner']['login']
                                get_memb = session.get(f'{github_api}/orgs/{org_name}/members')
                                # this assumes there won't be more than one page...
                                members = [m['login'] for m in get_memb.json()]
                        else:
                            dn = repo['owner']['ldap_dn']
                            members = 'not an org'
                        entry = {
                            "repo":repo_name,
                            "owner":repo['owner']['login'],
                            "owner_dn":dn,
                            "members":members,
                            "latest_commit":latest_commit_date,
                            "filename":i['name'],
                            "latest_file_commit":latest_file_commit_date,
                            "var_assignment":var_assign,
                            "fragment":context.encode("utf-8"),
                            "all_results_for_repo":all_results
                        }
                        # supressing output
                        _ = writer.writerow(entry)


# something like this... but doesn't really work...
def github_multi_search(output_dir, search_strs, github_url=github_url, api_token=None, context_padding=40):
    if api_token is None:
        api_token = getpass.getpass("API token:")
    if isinstance(search_strs, list):
        with Pool(processes=len(search_strs)) as pool:
            for s in search_strs:
                pool.starmap(github_code_search, (output_dir, s, github_url, api_token, context_padding))
    else:
        print(f'Expecting an array of search strings as search_str, received {search_strs}')

search_strs = ['pass','pwd','key','token']
# files named with search criteria to allow for easy multithreading if desired
github_code_search(output_dir=output_dir,search_str='key')
# github_multi_search(output_dir=output_dir, search_strs=search_strs)