#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pandas", "requests"]
# ///

import subprocess
import json
import argparse
import sys
import pandas as pd
from datetime import datetime

def run_gh_api(query):
    """Executes a GitHub GraphQL API query using the 'gh' CLI."""
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        return None
    return json.loads(result.stdout)

def fetch_repos():
    """Fetches a list of all repositories the user has access to."""
    print("Listing all repositories...", file=sys.stderr)
    result = subprocess.run(
        ["gh", "repo", "list", "--limit", "1000", "--json", "nameWithOwner,isPrivate,pushedAt,createdAt"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"Error listing repos: {result.stderr}", file=sys.stderr)
        return []
    return json.loads(result.stdout)

def fetch_viewer_id():
    """Fetches the current authenticated user's ID."""
    query = "{ viewer { id login } }"
    data = run_gh_api(query)
    if data and "data" in data:
        return data["data"]["viewer"]["id"]
    return None

def fetch_repo_details(repo_name, year, user_id):
    """Fetches commit counts and language breakdown for a specific repository in a given year."""
    start = f"{year}-01-01T00:00:00Z"
    end = f"{year}-12-31T23:59:59Z"
    owner, name = repo_name.split("/")
    
    query = f"""
    query {{
      repository(owner: "{owner}", name: "{name}") {{
        nameWithOwner
        isPrivate
        createdAt
        languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
          edges {{
            size
            node {{ name }}
          }}
        }}
        defaultBranchRef {{
          target {{
            ... on Commit {{
              history(since: "{start}", until: "{end}", author: {{id: "{user_id}"}}) {{
                totalCount
                nodes {{
                  occurredAt: committedDate
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    """
    return run_gh_api(query)

def fetch_calendar(year):
    """Fetches the contribution calendar."""
    start = f"{year}-01-01T00:00:00Z"
    end = f"{year}-12-31T23:59:59Z"
    query = f"""
    query {{
      viewer {{
        contributionsCollection(from: "{start}", to: "{end}") {{
          contributionCalendar {{
            totalContributions
            weeks {{
              contributionDays {{
                date
                contributionCount
              }}
            }}
          }}
        }}
      }}
    }}
    """
    return run_gh_api(query)

def print_ascii_chart(data, title):
    """Prints a simple ASCII bar chart."""
    print(f"\n=== {title} ===")
    if data.empty:
        print("No data available.")
        return
    max_val = data.max()
    for index, value in data.items():
        bar_len = int((value / max_val) * 50) if max_val > 0 else 0
        bar = "█" * bar_len
        print(f"{str(index):10} | {bar} ({int(value)})")

def redact_name(name_with_owner, is_private):
    """Redacts private repository names: jeffjose/formula1 -> jeffjose/fxxxxxx1"""
    if not is_private:
        return name_with_owner
    try:
        owner, name = name_with_owner.split("/")
        if len(name) <= 2:
            redacted = "x" * len(name)
        else:
            redacted = name[0] + "x" * (len(name) - 2) + name[-1]
        return f"{owner}/{redacted}"
    except Exception:
        return name_with_owner

def main():
    parser = argparse.ArgumentParser(description="Unified GitHub Behavior Analytics")
    parser.add_argument("--years", type=str, default="2020,2021,2022,2023,2024,2025,2026", help="Comma separated years")
    parser.add_argument("--mode", choices=["all", "monthly", "language", "repos", "temporal", "births"], default="all", help="Mode")
    parser.add_argument("--save", action="store_true", help="Save to CSV")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(",")]
    all_data = []
    repo_creation_dates = {}
    
    user_id = fetch_viewer_id()
    if not user_id: return
    repos = fetch_repos()
    
    for year in years:
        print(f"\nProcessing {year}...", file=sys.stderr)
        cal_data = fetch_calendar(year)
        if cal_data and "data" in cal_data:
            calendar = cal_data["data"]["viewer"]["contributionsCollection"]["contributionCalendar"]
            for week in calendar["weeks"]:
                for day in week["contributionDays"]:
                    all_data.append({"type": "activity", "year": year, "date": day["date"], "count": day["contributionCount"]})

        # 3. Get Per-Repo Stats (Commits, Languages, Temporal)
        # Only check repos that were pushed to in or after the target year
        active_repos = [r for r in repos if r["pushedAt"][:4] >= str(year)]
        
        for r_meta in active_repos:
            repo_name = r_meta["nameWithOwner"]
            print(f"  Fetching {repo_name}...", end="\r", file=sys.stderr)
            raw = fetch_repo_details(repo_name, year, user_id)
            if not raw or "data" not in raw or not raw["data"]["repository"]: continue
            repo = raw["data"]["repository"]
            
            is_private = repo["isPrivate"]
            display_name = redact_name(repo_name, is_private)
            
            repo_creation_dates[display_name] = repo["createdAt"]
            if not repo["defaultBranchRef"]: continue
            history = repo["defaultBranchRef"]["target"]["history"]
            total_commits = history["totalCount"]
            if total_commits == 0: continue
            
            for commit in history["nodes"]:
                dt = datetime.strptime(commit["occurredAt"], "%Y-%m-%dT%H:%M:%SZ")
                all_data.append({"type": "temporal", "year": year, "hour": dt.hour, "weight": 1})
            
            langs = repo["languages"]["edges"]
            total_size = sum(l["size"] for l in langs)
            for l in langs:
                weight = l["size"] / total_size if total_size > 0 else 0
                all_data.append({
                    "type": "coding", "year": year, "repo": display_name, "is_private": is_private,
                    "language": l["node"]["name"], "commits_weighted": total_commits * weight,
                    "loc_approx": (l["size"] / 50)
                })

    if not all_data: return
    df = pd.DataFrame(all_data)
    if args.save:
        df.to_csv("github_raw_stats.csv", index=False)
        print("\n[INFO] Saved to github_raw_stats.csv")

    if args.mode in ["all", "monthly"]:
        act = df[df["type"] == "activity"].copy()
        act["month"] = pd.to_datetime(act["date"]).dt.to_period("M")
        print_ascii_chart(act.groupby("month")["count"].sum(), "Monthly Activity")

    if args.mode in ["all", "temporal"]:
        print_ascii_chart(df[df["type"] == "temporal"].groupby("hour")["weight"].sum(), "Activity by Hour (UTC)")

    if args.mode in ["all", "births"]:
        births = pd.Series(repo_creation_dates).apply(lambda x: x[:4])
        print_ascii_chart(births.value_counts().sort_index(), "Repo Birth Rate")

    if args.mode in ["all", "language"]:
        coding = df[df["type"] == "coding"]
        trend = coding.groupby(["year", "language"])["commits_weighted"].sum().unstack(fill_value=0)
        print("\n=== Language Trend ===\n", trend[trend.sum().sort_values(ascending=False).index[:10]].round(1))

    if args.mode in ["all", "repos"]:
        coding = df[df["type"] == "coding"]
        print("\n=== Top Repos ===\n", coding.groupby("repo").agg({"commits_weighted": "sum", "loc_approx": "sum", "is_private": "first"}).sort_values("commits_weighted", ascending=False).head(10).round(0))

if __name__ == "__main__":
    main()