#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///
import subprocess
import sys
import shlex
import os

def get_commits(filename, file_dir, file_base):
    """Returns a list of dicts with commit hash, date, and message."""
    try:
        # Get list of commits for the specific file
        cmd = ['git', 'log', '--pretty=format:%H|%ad|%s', '--date=short', '--', file_base]
        output = subprocess.check_output(cmd, text=True, cwd=file_dir).strip()
        if not output:
            return []
        lines = output.split('\n')
        commits = []
        for line in lines:
            parts = line.split('|', 2)
            if len(parts) == 3:
                commits.append({'hash': parts[0], 'date': parts[1], 'msg': parts[2]})
        return commits
    except subprocess.CalledProcessError:
        return []

def view_file(commit_hash, file_dir, file_base):
    """Pipes the file content at a specific commit to less."""
    # We use ./ prefix to ensure git interprets it as a path relative to current dir
    cmd = f"git show {commit_hash}:./{shlex.quote(file_base)} | less"
    subprocess.call(cmd, shell=True, cwd=file_dir)

def view_diff(commit_hash, file_dir, file_base):
    """Shows the changes to the file in this commit."""
    subprocess.call(['git', 'show', commit_hash, '--', file_base], cwd=file_dir)

def main():
    if len(sys.argv) < 2:
        print("Usage: git-step <filename>")
        sys.exit(1)
        
    target_path = sys.argv[1]
    if not os.path.exists(target_path):
        print(f"Error: File '{target_path}' not found.")
        sys.exit(1)

    # Resolve absolute paths and directory
    abs_path = os.path.abspath(target_path)
    file_dir = os.path.dirname(abs_path)
    file_base = os.path.basename(abs_path)
    
    # Verify file is tracked or has history
    commits = get_commits(target_path, file_dir, file_base)
    
    if not commits:
        print(f"No commit history found for '{file_base}'.")
        sys.exit(1)
        
    index = 0
    total = len(commits)
    
    while True:
        commit = commits[index]
        
        # Header Info
        print(f"\nFile: \033[1m{file_base}\033[0m")
        print(f"Commit {index + 1}/{total}")
        print(f"Hash: \033[33m{commit['hash'][:7]}\033[0m ({commit['date']})")
        print(f"Msg:  {commit['msg']}")
        print("-" * 60)
        
        # Navigation Menu
        # Note: git log is ordered newest to oldest.
        # So index + 1 is 'older' (back in time), index - 1 is 'newer' (forward in time).
        options = []
        options.append("[v]iew content")
        options.append("[d]iff changes")
        
        nav_info = []
        if index < total - 1:
            nav_info.append("[n]ext (older)")
        if index > 0:
            nav_info.append("[p]rev (newer)")
            
        nav_str = " | ".join(nav_info)
        print(f"Actions: [v]iew | [d]iff | {nav_str} | [q]uit")
        
        try:
            choice = input("> ").lower().strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
            
        if choice == 'q':
            break
        elif choice == 'v':
            view_file(commit['hash'], file_dir, file_base)
        elif choice == 'd':
            view_diff(commit['hash'], file_dir, file_base)
        elif choice == 'n':
            if index < total - 1:
                index += 1
            else:
                print(">> This is the oldest commit.")
        elif choice == 'p':
            if index > 0:
                index -= 1
            else:
                print(">> This is the latest commit.")
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()
