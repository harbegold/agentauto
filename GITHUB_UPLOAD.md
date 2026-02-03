# Upload to GitHub

Your repo is initialized and committed. Follow these steps to push to GitHub.

## 1. Create a new repository on GitHub

1. Go to **https://github.com/new**
2. **Repository name:** e.g. `agent-automation` or `browser-navigation-challenge`
3. **Description (optional):** e.g. "Browser Navigation Challenge agent – 30 steps in under 5 min"
4. Choose **Public**
5. **Do not** check "Add a README" or "Add .gitignore" (you already have them)
6. Click **Create repository**

## 2. Add the remote and push

GitHub will show you commands. Use these (replace `YOUR_USERNAME` and `YOUR_REPO` with your actual values):

```powershell
cd "c:\Users\harry\Documents\agent automation"

# Add your GitHub repo as "origin" (replace with your repo URL)
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git

# Push (first time: set upstream for master)
git push -u origin master
```

**Example** if your username is `harry` and repo is `agent-automation`:

```powershell
git remote add origin https://github.com/harry/agent-automation.git
git push -u origin master
```

## 3. If you use SSH instead of HTTPS

```powershell
git remote add origin git@github.com:YOUR_USERNAME/YOUR_REPO.git
git push -u origin master
```

## 4. After pushing

- Claude (or anyone) can clone with:  
  `git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git`
- Give Claude the repo URL and point it to **CLAUDE_HANDOFF_NOTE.md** for context.

## Note

- **out/** is in `.gitignore` (run logs, videos, traces are not pushed).
- **.venv312/** is ignored (virtualenv stays local).
