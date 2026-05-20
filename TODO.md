# TODO

## Branch cleanup (remaining)

All work was consolidated into a single `main` branch. One manual step
remains because GitHub will not let you delete a repository's default
branch, and the old `claude/csafe-fitness-server-xPaba` branch is still
set as the default.

- [ ] On GitHub: **Settings → General → Default branch** → switch the
      default to `main`.
- [ ] Delete the old default branch once it is no longer the default:
      - Via GitHub Branches page (delete button), or
      - Locally: `git push origin --delete claude/csafe-fitness-server-xPaba`

## Going forward

- Once the steps above are done, **`main` is the only branch we work off of.**
- There are no other branches to merge — everything is already on `main`.
