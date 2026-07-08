#!/usr/bin/env python3
import os
import json
import re
import subprocess
import sys

# Ensure stdout/stderr use UTF-8, especially on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


def get_version_from_filename(filename, slug):
    if not filename:
        return "unknown"
    name = re.sub(r'\.(jar|zip|mrpack)$', '', filename, flags=re.IGNORECASE)
    parts = name.split('-')
    for i, part in enumerate(parts):
        if part and part[0].isdigit():
            subparts = parts[i:]
            filtered = []
            for sp in subparts:
                if sp.lower() in ('fabric', 'forge', 'neoforge', 'quilt') or re.match(r'^(mc)?1\.\d+(\.\d+)?$', sp.lower()):
                    continue
                filtered.append(sp)
            return "-".join(filtered) if filtered else part
    match = re.search(r'(\d+[\w\.\+\-]+)', name)
    if match:
        return match.group(1)
    return name

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def run_cmd(args):
    return subprocess.check_output(args).decode("utf-8").strip()

def main():
    print("🔎 Gathering modpack metadata...")
    
    # 1. Load pakku.json
    if not os.path.exists("pakku.json"):
        print("::error::Could not find pakku.json")
        sys.exit(1)
    pakku_data = load_json("pakku.json")
    project_name = pakku_data.get("name", "CivPack")
    version = pakku_data.get("version", "1.0.0")
    description = pakku_data.get("description", "")
    
    # 2. Load pakku-lock.json
    if not os.path.exists("pakku-lock.json"):
        print("::error::Could not find pakku-lock.json")
        sys.exit(1)
    lock_data = load_json("pakku-lock.json")
    
    # Game versions & loaders
    game_versions = ",".join(lock_data.get("mc_versions", []))
    loaders = ",".join([l.lower() for l in lock_data.get("loaders", {}).keys()])
    if not loaders:
        loaders = "fabric" # Fallback
        
    # 3. Determine release type
    rel_type = "release"
    version_lower = version.lower()
    if "alpha" in version_lower:
        rel_type = "alpha"
    elif "beta" in version_lower:
        rel_type = "beta"
        
    # 4. Get Git Tags and Previous Commit
    github_ref = os.environ.get("GITHUB_REF", "")
    github_ref_name = os.environ.get("GITHUB_REF_NAME", "")
    
    tag = github_ref_name if github_ref.startswith("refs/tags/") else version
    
    # Try to find previous tag
    latest_tag = None
    try:
        latest_tag = run_cmd(["git", "describe", "--tags", "--abbrev=0"])
    except Exception:
        pass
        
    if latest_tag and github_ref.startswith("refs/tags/") and latest_tag == github_ref_name:
        try:
            latest_tag = run_cmd(["git", "describe", "--tags", "--abbrev=0", "HEAD^"])
        except Exception:
            latest_tag = None
            
    if not latest_tag:
        try:
            # Fallback to the first commit in the repository
            latest_tag = run_cmd(["git", "rev-list", "--max-parents=0", "HEAD"]).split('\n')[0]
        except Exception:
            pass
            
    print(f"Current version: {version}")
    print(f"Tag: {tag}")
    print(f"Comparing against previous ref: {latest_tag}")
    
    # 5. Extract Previous pakku-lock.json and Generate Diff
    diff_content = ""
    if latest_tag:
        try:
            prev_lock_content = run_cmd(["git", "show", f"{latest_tag}:pakku-lock.json"])
            with open("pakku-lock-prev.json", "w", encoding="utf-8") as f:
                f.write(prev_lock_content)
                
            # Perform Python-based diff comparison
            old_lock = load_json("pakku-lock-prev.json")
            old_projects = {p["pakku_id"]: p for p in old_lock.get("projects", [])}
            new_projects = {p["pakku_id"]: p for p in lock_data.get("projects", [])}
            
            added = []
            removed = []
            updated = []
            
            for pid, proj in new_projects.items():
                name = proj.get("name", {}).get("modrinth") or proj.get("name", {}).get("curseforge") or proj.get("slug", {}).get("modrinth") or pid
                slug = proj.get("slug", {}).get("modrinth") or proj.get("slug", {}).get("curseforge")
                
                if proj.get("slug", {}).get("modrinth"):
                    url = f"https://modrinth.com/mod/{proj['slug']['modrinth']}"
                elif proj.get("slug", {}).get("curseforge"):
                    url = f"https://www.curseforge.com/minecraft/mc-mods/{proj['slug']['curseforge']}"
                else:
                    url = None
                    
                link_str = f"**[{name}]({url})**" if url else f"**{name}**"
                
                if pid not in old_projects:
                    added.append(f"- {link_str}")
                else:
                    old_proj = old_projects[pid]
                    old_file = old_proj.get("files", [{}])[0].get("file_name", "")
                    new_file = proj.get("files", [{}])[0].get("file_name", "")
                    if old_file != new_file:
                        old_ver = get_version_from_filename(old_file, slug)
                        new_ver = get_version_from_filename(new_file, slug)
                        updated.append(f"- {link_str} (`{old_ver}` ➔ `{new_ver}`)")
                        
            for pid, proj in old_projects.items():
                if pid not in new_projects:
                    name = proj.get("name", {}).get("modrinth") or proj.get("name", {}).get("curseforge") or pid
                    slug = proj.get("slug", {}).get("modrinth") or proj.get("slug", {}).get("curseforge")
                    if proj.get("slug", {}).get("modrinth"):
                        url = f"https://modrinth.com/mod/{proj['slug']['modrinth']}"
                    elif proj.get("slug", {}).get("curseforge"):
                        url = f"https://www.curseforge.com/minecraft/mc-mods/{proj['slug']['curseforge']}"
                    else:
                        url = None
                    link_str = f"**[{name}]({url})**" if url else f"**{name}**"
                    removed.append(f"- {link_str}")
                    
            if added:
                diff_content += "### Added Mods\n" + "\n".join(added) + "\n\n"
            if updated:
                diff_content += "### Updated Mods\n" + "\n".join(updated) + "\n\n"
            if removed:
                diff_content += "### Removed Mods\n" + "\n".join(removed) + "\n\n"
        except Exception as e:
            print(f"Warning: Failed to generate lockfile diff: {e}")
            diff_content = "*(First release / No previous lockfile diff available)*"
            
    # 6. Parse and Update CHANGELOG.md
    changelog_path = "CHANGELOG.md"
    news_content = ""
    if os.path.exists(changelog_path):
        with open(changelog_path, "r", encoding="utf-8") as f:
            changelog_text = f.read()
            
        # Extract news block
        # Match @news@{ <content> }
        news_match = re.search(r'@news@\{\s*\n*([\s\S]*?)\n?\s*\}', changelog_text)
        if news_match:
            news_content = news_match.group(1).strip()
            
        # Replace placeholders in changelog
        final_changelog = changelog_text
        final_changelog = final_changelog.replace("@mod_changes@", diff_content)
        # Remove the outer @news@{ } wrapping and replace it with just the news_content
        final_changelog = re.sub(r'@news@\{\s*\n*([\s\S]*?)\n?\s*\}', news_content, final_changelog)
        final_changelog = final_changelog.replace("@version@", version)
        
        # Write suffix changelog
        output_changelog_path = f"CHANGELOG-{version}.md"
        with open(output_changelog_path, "w", encoding="utf-8") as f:
            f.write(final_changelog)
        print(f"Generated {output_changelog_path}")
    else:
        # Create a simple fallback changelog
        output_changelog_path = f"CHANGELOG-{version}.md"
        fallback_content = f"# CivPack {version}\n\n## Mod Changes\n\n{diff_content}"
        with open(output_changelog_path, "w", encoding="utf-8") as f:
            f.write(fallback_content)
        print(f"No CHANGELOG.md found. Generated fallback {output_changelog_path}")
        
    # Write to GitHub Actions outputs
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"projectname={project_name}\n")
            f.write(f"version={version}\n")
            f.write(f"tag={tag}\n")
            f.write(f"rel_type={rel_type}\n")
            f.write(f"game_versions={game_versions}\n")
            f.write(f"loaders={loaders}\n")
            # For multiline output in GitHub Actions
            f.write("news<<EOF\n")
            f.write(f"{news_content}\n")
            f.write("EOF\n")
            
    # Write step summary
    github_step_summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if github_step_summary:
        with open(github_step_summary, "a", encoding="utf-8") as f:
            f.write(f"### Modpack Build: {project_name} v{version}\n")
            f.write(f"- **Compatible Minecraft Versions:** {game_versions}\n")
            f.write(f"- **Compatible Loaders:** {loaders}\n")
            f.write(f"- **Release Type:** {rel_type}\n\n")
            f.write("#### Changelog Preview\n")
            if news_content:
                f.write(f"**What's new:**\n{news_content}\n\n")
            f.write(diff_content)
            
    print("Metadata extraction complete.")

if __name__ == "__main__":
    main()
