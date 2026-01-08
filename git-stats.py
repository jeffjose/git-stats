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

def fetch_stats(year):
    """Fetches contribution, repository, and temporal stats for a given year."""
    start = f"{year}-01-01T00:00:00Z"
    end = f"{year}-12-31T23:59:59Z"
    
    query = f"""
    query {{
      viewer {{
        contributionsCollection(from: "{start}", to: "{end}") {{
          totalCommitContributions
          commitContributionsByRepository(maxRepositories: 100) {{
            repository {{
              nameWithOwner
              isPrivate
              createdAt
              languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
                edges {{
                  size
                  node {{ name }}
                }}
              }}
            }}
            contributions(first: 100) {{
              nodes {{
                occurredAt
                commitCount
              }}
            }}
          }}
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

def main():
    parser = argparse.ArgumentParser(description="Unified GitHub Behavior Analytics")
    parser.add_argument("--years", type=str, default="2020,2021,2022,2023,2024,2025", help="Comma separated years to analyze")
    parser.add_argument("--mode", choices=["all", "monthly", "language", "repos", "temporal", "births"], default="all", help="Analysis mode")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(",")]
    all_data = []
    repo_creation_dates = {}
    
    for year in years:
        print(f"Fetching data for {year}...", file=sys.stderr)
        raw = fetch_stats(year)
        if not raw or "data" not in raw: continue
        
        coll = raw["data"]["viewer"]["contributionsCollection"]
        
        # 1. Daily Activity
        calendar = coll["contributionCalendar"]
        for week in calendar["weeks"]:
            for day in week["contributionDays"]:
                all_data.append({
                    "type": "activity",
                    "year": year,
                    "date": day["date"],
                    "count": day["contributionCount"]
                })

        # 2. Repo, Language, Temporal, and LOC data
        for entry in coll["commitContributionsByRepository"]:
            repo = entry["repository"]
            name = repo["nameWithOwner"]
            repo_creation_dates[name] = repo["createdAt"]
            
            commits_nodes = entry["contributions"]["nodes"]
            total_commits = sum(c["commitCount"] for c in commits_nodes)
            
            # Temporal - Hour of Day
            for c_node in commits_nodes:
                dt = datetime.strptime(c_node["occurredAt"], "%Y-%m-%dT%H:%M:%SZ")
                all_data.append({
                    "type": "temporal",
                    "year": year,
                    "hour": dt.hour,
                    "weight": c_node["commitCount"]
                })
            
            langs = repo["languages"]["edges"]
            total_size = sum(l["size"] for l in langs)
            
            for l in langs:
                weight = l["size"] / total_size if total_size > 0 else 0
                all_data.append({
                    "type": "coding",
                    "year": year,
                    "repo": name,
                    "language": l["node"]["name"],
                    "commits_weighted": total_commits * weight,
                    "loc_approx": (l["size"] / 50) # Very rough heuristic: 50 bytes per line per language
                })

    if not all_data:
        print("No data fetched. Check your 'gh' auth status.")
        return

    df = pd.DataFrame(all_data)
    
    # Monthly View
    if args.mode in ["all", "monthly"]:
        activity_df = df[df["type"] == "activity"].copy()
        activity_df["month"] = pd.to_datetime(activity_df["date"]).dt.to_period("M")
        monthly_totals = activity_df.groupby("month")["count"].sum()
        print_ascii_chart(monthly_totals, "Monthly Activity Trend")

    # Temporal View
    if args.mode in ["all", "temporal"]:
        temporal_df = df[df["type"] == "temporal"]
        hour_dist = temporal_df.groupby("hour")["weight"].sum()
        print_ascii_chart(hour_dist, "Activity by Hour of Day (UTC)")

    # Repo Births View
    if args.mode in ["all", "births"]:
        births = pd.Series(repo_creation_dates).apply(lambda x: datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ").year)
        births_count = births.value_counts().sort_index()
        print_ascii_chart(births_count, "Repository Birth Rate (New Repos per Year)")

    # Language View
    if args.mode in ["all", "language"]:
        coding_df = df[df["type"] == "coding"]
        lang_trend = coding_df.groupby(["year", "language"])["commits_weighted"].sum().unstack(fill_value=0)
        top_langs = lang_trend.sum().sort_values(ascending=False).index[:10]
        print("\n=== Language Trend (Weighted Commits) ===")
        print(lang_trend[top_langs].round(1))

    # Repos and LOC View
    if args.mode in ["all", "repos"]:
        coding_df = df[df["type"] == "coding"]
        repo_stats = coding_df.groupby("repo").agg({"commits_weighted": "sum", "loc_approx": "sum"}).sort_values("commits_weighted", ascending=False).head(10)
        print("\n=== Top Repositories (Commits & Approx LOC) ===")
        print(repo_stats.round(0))

if __name__ == "__main__":
    main()
