# Oddtoon Uploader

Local web app for uploading and scheduling videos to the Oddtoon YouTube channel. The UI is modelled on YouTube Studio. Before anything is uploaded, every video goes through checks for YouTube's API limits and spam rules.

## Run

1. Put `client_secret.json` (a Google Cloud OAuth client of type Desktop) in `credentials/`.
2. Double-click `Start.bat`. The first run installs dependencies into `.venv`.
3. In the browser tab that opens, click **Connect YouTube** and pick the channel.

Videos live in `videos/`. Each video gets a `<name>.json` file next to it for metadata, plus an optional `<name>.thumb.jpg` thumbnail. Old ZorvoST `.txt` files are imported automatically, minus their keyword lists.

## Features

- Content table: drag in videos, edit details, see each video's checks, upload several at once with progress and automatic retry.
- Details dialog modelled on Studio: title, description, tags, category, audience (made for kids), altered-content disclosure, visibility and schedule.
- Checks before upload:
  - Errors that block the upload: title over 100 characters, description over 5000, `<` or `>` in either, tags over 500 characters, more than 60 hashtags, pasted keyword lists, a schedule time in the past.
  - Warnings: over-tagging, repeated keywords, all-caps or `!!!` titles, Shorts longer than 3 minutes or not vertical.
- Auto-schedule: puts each video in the next free daily slot, in the audience's time zone. It skips times already taken locally or on YouTube.
- Insights: views by weekday, top countries, and first-week views by publish hour. The best-hour suggestion appears once there are enough videos to compare.
- Quota meter: a local estimate against the 10,000 units/day limit. One upload costs about 1600 units.

## Gotchas

- **API audit.** Videos uploaded from an unaudited Google Cloud project are locked to Private. The app detects this and flags it. Apply at https://support.google.com/youtube/contact/yt_api_form.
- **Testing mode.** While the OAuth app is in Testing, the refresh token expires after 7 days, so you have to reconnect.
- Custom thumbnails need a phone-verified channel.

## Dev

```
.venv\Scripts\python -m pytest -q tests
.venv\Scripts\python -m app
```
