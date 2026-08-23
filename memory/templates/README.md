# Jarvis vault

This folder is the filing cabinet, not the live chat. Talk only loads `BOOT.md` plus today’s (and maybe yesterday’s) daily note. Everything else is for a workbench to read on demand.

This directory is meant to be a **private git repo**. After the first Talk run:

```
cd ~/.jarvis/vault
git remote add origin git@github.com:YOU/jarvis-vault.git
git add -A && git commit -m "boot vault" && git push -u origin main
```

Do not put tokens or passwords in these files. Do not sync `~/.grok/sessions/`.
