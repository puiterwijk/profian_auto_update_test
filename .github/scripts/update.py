#!/usr/bin/env python3
import os
import sys
import time
import urllib.parse

from git import Repo
from github import Github
from yaml import safe_load, safe_dump


MAX_PR_WAIT = 60
MAIN_BRANCH = "main"
REQUIRED_CHECKS_PR = [
]
REQUIRED_CHECKS_DEPLOY = [
]


def get_gh_full_name(repo):
    return urllib.parse.urlparse(repo.remote().url).path[1:].removesuffix(".git")


def get_pr_head(pr):
    return pr.get_commits().reversed[0]


def create_branch(repo, environment, service, new_version):
    branch_name = f"upgrade-{service}-{new_version}-{environment}"
    print(f"Creating branch {branch_name}")

    new_branch = repo.create_head(branch_name)
    new_branch.checkout()

    return branch_name


def update_file(environment, service, new_version):
    filename = f"apps/{environment}/{service}/patch-deployment.yaml"

    with open(filename) as f:
        contents = safe_load(f)

    print("Old file:", contents)

    if new_version.startswith("sha256:"):
        new_image = f"ghcr.io/profianinc/{service}@{new_version}"
    else:
        new_image = f"ghcr.io/profianinc/{service}:{new_version}"

    contents["spec"]["template"]["spec"]["containers"][0]["image"] = new_image

    print("New file:", contents)

    with open(filename, "w") as f:
        safe_dump(contents, f)

    return filename


def commit(repo, filename, environment, service, new_version):
    repo.index.add([filename])

    diff = repo.head.commit.diff()
    if len(diff) == 0:
        print("No changes, skipping commit")
        return False

    repo.index.commit(f"Upgrade {service} to {new_version} in {environment}")

    print("Commit created: ", repo.head.commit)

    return True


def push(repo, branch_name, environment, service, new_version):
    origin = repo.remote("origin")
    origin.push(branch_name).raise_if_error()

    print("Pushed branch to GitHub")


def create_pr(gh_repo, branchname, environment, service, new_version):
    pr = gh_repo.create_pull(
        title=f"Upgrade {service} to {new_version} in {environment}",
        body=f"Upgrade {service} to {new_version} in {environment}",
        head=branchname,
        base=MAIN_BRANCH,
    )

    print(f"Created pull request {pr}")

    return pr


def wait_for_commit_checks(commit, required_checks):
    print("Waiting for commit checks to complete")

    start_time = time.time()

    while True:
        if time.time() - start_time >= MAX_PR_WAIT:
            raise Exception(f"Timed out waiting for PR checks ({MAX_PR_WAIT} seconds)")

        required_pending = set(required_checks)

        any_pending = False

        check_runs = pr_head.get_check_runs()
        if check_runs.totalCount == 0:
            print("Check runs not yet scheduled, waiting")
            continue
        for run in check_runs:
            if run.status != "completed":
                any_pending = True
                print(f"Check run {run} pending")
                continue
            if run.conclusion != "success":
                raise Exception(f"Check run {run} failed")
            if run.name in required_pending:
                required_pending.remove(run.name)

        statuses = pr_head.get_statuses()
        for status in statuses:
            if status.state == "pending":
                any_pending = True
                print(f"Status {status.context} pending")
                continue
            if status.state != "success":
                raise Exception(f"Status {status.context} failed")

        if any_pending:
            print("Check runs pending, waiting")
            continue

        if required_pending:
            print(f"Required checks {required_pending} not yet scheduled")
            continue

        break

    print("All checks passed")


def merge_pr(github_merge, pr):
    print("Merging PR")
    result = pr.merge()
    if not result.merged:
        raise Exception(f"PR merge failed: {result}")


def perform_environment(repo, github_create, github_merge, environment, service, new_version):
    print(f"Updating {environment}")

    branchname = create_branch(repo, environment, service, new_version)
    fname = update_file(environment, service, new_version)
    if not commit(repo, fname, environment, service, new_version):
        # This method returns True if there were changes, and False if there were
        # no changes. If there were no changes, this environment is already
        # running the latest version, so we don't need to push the branch
        # to GitHub.
        return
    push(repo, branchname, environment, service, new_version)
    pr = create_pr(github_create, branchname, environment, service, new_version)
    pr_head = get_pr_head(pr)
    wait_for_commit_checks(pr_head, REQUIRED_CHECKS_PR)
    if environment == "production":
        print("Not merging PR to production")
        return
    merge_pr(github_merge, pr)

    main_git_ref = github_create.get_git_ref(f"heads/{MAIN_BRANCH}")
    print("Waiting for main branch checks to complete")
    wait_for_commit_checks(main_git_ref.object.sha, REQUIRED_CHECKS_MAIN)
    print(f"Environment {environment} updated succesfully")


def main():
    if len(sys.argv) != 4:
        print("Usage: upgrade.py <environment> <service> <new_version>")
        sys.exit(1)
    highest_environment, service, new_version = sys.argv[1:]

    if highest_environment == "testing":
        envs = ["testing"]
    elif highest_environment == "staging":
        #envs = ["testing", "staging"]
        envs = ["staging"]
    elif highest_environment == "production":
        envs = ["testing", "staging", "production"]

    print(f"Upgrading {service} to {new_version} in envs {envs}")

    repo = Repo(".")
    start_branch = repo.head.ref

    repo_name = get_gh_full_name(repo)

    gh_token = os.environ["GITHUB_TOKEN"]
    github_create = Github(gh_token).get_repo(repo_name)

    # TODO
    github_merge = None

    print("GitHub repo (create):", github_create)
    print("GitHub repo (merge):", github_merge)

    for env in envs:
        start_branch.checkout()
        origin = repo.remote("origin").pull()

        perform_environment(repo, github_create, github_merge, env, service, new_version)


if __name__ == "__main__":
    main()
