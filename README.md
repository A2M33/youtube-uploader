# YouTube Uploader

Upload and schedule YouTube videos from a local web app or from the command line. The CLI prints JSON and returns clear exit codes, so an AI agent (Claude Code, Codex, a script) can upload a video in one command. Every upload goes through checks for YouTube's API limits and spam rules first.

## Setup

1. Create a Google Cloud OAuth client of type **Desktop**, with the YouTube Data API v3 and YouTube Analytics API enabled. Save it as `credentials/client_secret.json`.
2. Run `Install.bat` (or `python -m venv .venv` and `.venv\Scripts\pip install -r requirements.txt`).
3. Sign in once: `.venv\Scripts\python -m app connect`, or press **Connect YouTube** in the web app. You pick the channel in the browser.

## Command line

```
.venv\Scripts\python -m app status
.venv\Scripts\python -m app upload D:\renders\clip.mp4 --title "The Army That Lost to Birds" ^
    --description-file desc.txt --tags "history,animation" --publish-at auto
```

`upload` copies the file into the videos folder, saves the metadata, runs the checks, uploads, and prints the video id and URLs. It refuses to upload a video twice.

| Command | What it does |
|---|---|
| `status` | Sign-in state, channel, quota left today, videos folder |
| `connect` | Google sign-in in the browser |
| `list [--all]` | Videos not uploaded yet, with check results |
| `meta <video> [flags]` | Show or set metadata without uploading |
| `check <video> [flags]` | Run the checks; exit 1 on errors |
| `upload <video> [flags] [--dry-run]` | Check and upload, wait for the result |
| `schedule <video>...` | Give videos the next free publish slots |
| `slots [--count N]` | List free publish slots |
| `uploads [--limit N]` | Latest videos on the channel |

Metadata flags: `--title`, `--description`, `--description-file`, `--tags`, `--category`, `--kids/--no-kids`, `--ai-content/--no-ai-content`, `--notify/--no-notify`, `--privacy public|unlisted|private`, `--publish-at <ISO time with zone>|auto`, `--thumbnail`, `--meta-json`.

Exit codes: `0` ok, `1` failed or blocked by checks, `2` setup or sign-in needed, `3` YouTube quota used up.

Instructions for AI agents live in [AGENTS.md](AGENTS.md).

## Web app

Double-click `Start.bat`. It has a content table with drag-and-drop, a details dialog laid out like YouTube Studio, a two-week schedule calendar, an insights page (views by weekday, top countries, first-week views by publish hour) and settings.

## Videos and metadata

Videos live in `videos/` by default. Point the app at another folder with `videos_dir` in `data/settings.json` or the `YT_UPLOADER_VIDEOS` environment variable.

Each video `<name>.mp4` can have `<name>.json` next to it with `title`, `description`, `tags`, `category_id`, `made_for_kids`, `synthetic_media`, `privacy`, `publish_at` and `notify_subscribers`, plus an optional `<name>.thumb.jpg`. The app also reads old `.txt` files (`TITLE:` / `TAGS:` / `PUBLISH_AT:` / `DESCRIPTION:`) and drops their keyword lists.

## Checks

Errors block the upload: an empty title or one over 100 characters, a description over 5000, `<` or `>` in either, tags over 500 characters, more than 60 hashtags, a pasted keyword list, a schedule time in the past.

Warnings: too many tags or hashtags, repeated keywords, all-caps or `!!!` titles, Shorts over 3 minutes or not vertical.

## Limits to know

- **Quota.** YouTube gives 10,000 units a day and one upload costs about 1,600, so you get about six uploads a day. The count resets at midnight Pacific.
- **API audit.** Google locks videos from an unaudited Cloud project to Private. The app flags this. Apply at https://support.google.com/youtube/contact/yt_api_form.
- **Testing mode.** While the OAuth app is in Testing, the sign-in expires after 7 days.
- Custom thumbnails need a phone-verified channel.

## Development

```
.venv\Scripts\python -m pytest -q tests
```
