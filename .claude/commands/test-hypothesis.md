Run the full hypothesis testing pipeline for the given hypothesis ID (e.g. H1, H2).

## Steps — execute in order, do not skip any

### 0. Branch check — do this before anything else
```bash
git branch --show-current
git status
```
- If on `main` or `dev`: proceed to step 1.
- If on `hypothesis/HN` and that hypothesis is `[x]` in HYPOTHESES.md: **STOP**. Do not make any changes. Tell the user which branch they are on, and ask them to confirm the next hypothesis number before creating a new branch.
- If on `hypothesis/HN` and the hypothesis is `[~]` (in progress): confirm with the user that continuing on this branch is intentional before proceeding.
- If on any other branch: warn the user and ask before proceeding.

### 1. Ensure on dev, create feature branch
```bash
git checkout dev && git pull origin dev
git checkout -b hypothesis/H{n}
```
Replace `{n}` with the hypothesis number.

### 2. Read the hypothesis
Read `HYPOTHESES.md` and find the entry matching the given ID. Extract:
- The exact code change required
- The expected effect

### 3. Pre-run logging + mark in progress
- Invoke the `ml-tracker` agent to log the experiment start to `EXPERIMENT_LOG.md`. Pass the hypothesis description, expected effect, and current hyperparameters from `train.py`.
- Update `HYPOTHESES.md`: change status from `[ ]` to `[~]`
- Commit:
```bash
git add HYPOTHESES.md EXPERIMENT_LOG.md && git commit -m "H{n}: mark in progress"
```

### 4. Implement the code change
Make the minimum change described in the hypothesis. Read the relevant file(s) first.
- Commit:
```bash
git add <changed files> && git commit -m "H{n}: implement <short description>"
```

### 5. Push and run training
```bash
git push origin hypothesis/H{n}
```
Training command — check for Modal first, fall back to local:
```bash
# If modal_train.py exists:
.venv/bin/modal run modal_train.py
# Otherwise:
source .venv/bin/activate && python train.py 2>&1 | tee logs/hypothesis_run.log
```
Run with `run_in_background=True`. Do not wait — continue only when notified of completion.

### 6. Parse the result
- Modal output: extract final `val Sharpe = {x}` from task output
- Local fallback: read `logs/hypothesis_run.log`

### 7. Update records
- Update `HYPOTHESES.md`: set status `[~]` → `[x]`, fill in Result and Conclusion
- Invoke `ml-tracker` to close the experiment in `EXPERIMENT_LOG.md` with the result and conclusion
- Commit:
```bash
git add HYPOTHESES.md EXPERIMENT_LOG.md && git commit -m "H{n}: results — val Sharpe {x}"
```

### 8. Prompt user for merge decision
Present the result and ask:

> H{n} complete — val Sharpe {result} vs best {best}.
> What would you like to merge into dev?
> a) Merge all (code + docs) — hypothesis confirmed or worth keeping
> b) Docs only (cherry-pick) — discard code change, keep records
> c) Leave branch open — inconclusive, revisit later

Wait for user response before proceeding.

### 9. Execute merge

**Option a — merge all:**
```bash
git checkout dev
git merge hypothesis/H{n} --no-ff -m "Merge H{n}: val Sharpe {x}"
git push origin dev
git branch -d hypothesis/H{n} && git push origin --delete hypothesis/H{n}
```

**Option b — docs only (cherry-pick):**
```bash
git checkout dev
# Get commit hashes: commit 1 = mark in progress, commit 3 = results
git log --oneline hypothesis/H{n}
git cherry-pick <commit-1-hash>   # mark in progress commit
git cherry-pick <commit-3-hash>   # results commit
git push origin dev
git branch -d hypothesis/H{n} && git push origin --delete hypothesis/H{n}
```

**Option c — leave open:**
Update `HYPOTHESES.md` note to "inconclusive — branch hypothesis/H{n} kept open". No merge.

### 10. Send notification
```bash
osascript -e 'display notification "H{n} — val Sharpe {x}. {action taken}." with title "RL Agent" sound name "Glass"'
```
Replace placeholders with actual values.
