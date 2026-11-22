# GitHub and Streamlit deployment checklist

## Update the GitHub repository

Run these commands from the project root in Windows PowerShell or another shell with Git installed. Choose a branch name that fits your repository workflow.

```powershell
git status --short
git check-ignore app/data/verity.db
git ls-files app/data
```

Confirm no local database or secret file is already tracked. If a database was tracked previously, untrack it before pushing; `.gitignore` does not remove files already tracked.

```powershell
git switch -c verity-ai-v1.4.4-final
git add .env.example .gitignore README.md CHANGES.md TEST_RESULTS.md Test-results.txt requirements.txt requirements-dev.txt app.py app/config.py app/components app/services .streamlit/config.toml docs sample_data tests
git diff --cached --check
git status --short
git commit -m "Finalize Verity AI evidence verification"
git push -u origin verity-ai-v1.4.4-final
```

Open a pull request, review the staged diff, and merge using the repository's normal process. Never add `.env`, `.streamlit/secrets.toml`, `app/data/`, local databases, or API keys. The final ZIP is a delivery artifact and need not be committed to the source repository.

## Deploy to Streamlit Community Cloud

1. Push the reviewed branch to GitHub.
2. In Streamlit Community Cloud, create an app from the repository, select the branch, and set the main file to `app.py`.
3. In app settings, add server-side secrets:

   ```toml
   GROQ_API_KEY = "your-groq-key"
   TAVILY_API_KEY = "your-tavily-key"
   ```

4. Deploy, open the app in a separate browser session, and check the six pages and a non-sensitive sample PDF.
5. Confirm the current app reports provider failures separately from factual verdicts. Do not infer live API availability from offline test results.
6. Run `docs/TRAP_TEST.md` only when live API credentials are configured. Record the actual verdicts and any provider failures; do not substitute saved-report replay results for a live run.

Streamlit Cloud's local SQLite storage may reset on restart. The application has no authentication and is not suitable for confidential PDFs without additional access, storage, retention, and privacy controls.
