# Jarvis vault

This folder is the filing cabinet, not the live chat. Talk loads `BOOT.md`, today/yesterday, household, and a short project index. `calendar.md`, reminders, and the weather/news caches are the daily brief — Jarvis only uses that on a check-in or if you ask. Matching `projects/*.md` pages are given to the mouth when Matt names that work. Everything else is for a workbench to read on demand.

This directory is meant to be a **private git repo**. After the first Talk run:

```
cd ~/.jarvis/vault
git remote add origin git@github.com:YOU/jarvis-vault.git
git add -A && git commit -m "boot vault" && git push -u origin main
```

Do not put tokens or passwords in these files. Do not sync `~/.grok/sessions/`.
