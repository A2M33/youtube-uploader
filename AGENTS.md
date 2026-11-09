# Uploading videos with this tool (for AI agents)

Run everything from the repo root with the venv Python: `.venv\Scripts\python -m app <command>`
(macOS/Linux: `.venv/bin/python -m app <command>`). Each command prints one JSON document on stdout;
progress goes to stderr.

## Upload a video

1. `python -m app status` and read `auth`:
   - `connected`: go on.
   - `disconnected`: run `python -m app connect` and tell the user to finish the Google sign-in in
     the browser that opens. You cannot do this step yourself.
   - `no_client_secret`: stop and tell the user to put a Desktop OAuth client in
     `credentials/client_secret.json`.
   - `uploads_left_today` 0: stop; the quota resets at midnight Pacific.
2. Upload in one command:
   ```
   python -m app upload <path-to-video> --title "..." --description-file desc.txt --tags "a,b,c" --publish-at auto
   ```
   - `--publish-at auto` takes the next free daily slot. For a fixed time pass ISO 8601 with a
     zone (`2026-11-20T20:00:00Z`). For an immediate upload use `--privacy public|unlisted|private`.
   - Add `--dry-run` first if you are unsure; it saves metadata and runs the checks only.
3. Read the result: `youtube_id`, `url`, `studio_url`, `privacy`, `publish_at`, `warnings`.
   Report the URL and every warning to the user.

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | ok | report the result |
| 1 | failed or blocked by checks | read `error` and `checks`, fix the metadata, retry |
| 2 | setup or sign-in needed | follow step 1 |
| 3 | quota used up | stop and tell the user |

## Rules

- Never upload the same video twice. The tool refuses (exit 1 with `youtube_id`); report the id.
- Fix every check with level `error`. Fix `warn` checks unless the user said otherwise.
- Write a real description (a sentence or two) with 2-5 hashtags. Keyword lists fail the checks.
- Keep tags few and accurate.
- Set `--kids` only if the user says the video is made for kids.
- Set `--ai-content` when the video shows realistic people, places or events made or changed with
  AI. Cartoons do not count.
- A `warnings` entry saying YouTube locked the video to Private means the Google Cloud project has
  not passed the API audit. Tell the user; retrying does not help.
- Do not edit `credentials/`, `data/state.json` or `data/quota.json` by hand.

## Other commands

`list`, `meta <video> [flags]`, `check <video> [flags]`, `schedule <video>...`, `slots`, `uploads`.
`python -m app <command> --help` lists every flag.
