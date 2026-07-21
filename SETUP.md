# Post-create setup (delete this file when done)

A GitHub template copies **files, not settings**. After creating a repo from
`repo-template`, the file skeleton is in place but the repo is on GitHub
defaults. Apply fleet settings, then delete this file.

## 1. Fill in the skeleton

- `README.md` — name, description, keep the Claude co-authorship disclosure at
  the top.
- `CLAUDE.md` — persona, what-this-repo-is, conventions.
- `.github/workflows/claude-code-review.yml` — **replace the placeholder
  `review_prompt`** with one written for THIS repo. Do not ship the boilerplate.

## 2. Apply fleet settings

If the **org-level `fleet-baseline` ruleset** exists (see
`dotgithub/fleet-ops/`), branch protection is already inherited automatically —
skip the per-repo ruleset. Otherwise, and for the merge-button/topics that
rulesets don't cover, run the fleet script from `~/repos`:

```bash
dotgithub/fleet-ops/fleet-apply.sh --apply --repo <new-repo-name>
```

That sets squash-only merge + auto-merge + delete-branch-on-merge and ensures
the `lentago` + `claude` spine topics. Add this repo's signature topics by
hand:

```bash
gh repo edit lentago/<new-repo-name> --add-topic <signature-tag> ...
```

## 3. Add the repo to the fleet inventory

Add the new repo name to the Lentago Labs org list in `~/repos/CLAUDE.md`.

## 4. Delete this file

```bash
git rm SETUP.md && git commit -m "Remove template setup notes" && git push
```
