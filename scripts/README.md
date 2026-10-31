# Deploy, backup and restore

Three scripts keep the production server updated and recoverable:

| Script | Runs on | Purpose |
| --- | --- | --- |
| `deploy_on_server_with_ssh.sh` | your machine | Starts a deploy on the server over ssh (not tracked: it holds server details, see `.gitignore`) |
| `deploy_production.sh` | the server | Pull, build, back up, migrate, restart, log |
| `backup.sh` | the server (also by cron) | Dump the database, archive media, save `.env`, log it |
| `restore.sh` | the server | Restore a backup, optionally with its code (`--with-code`) or undo the last deploy (`--rollback`) |

All scripts that touch the server live in the repo, run from the project root (they `cd` there themselves) and read settings from the environment first, then `.env`, then built-in defaults.

---

## Quick reference

```bash
# deploy the latest main (from your machine)
./scripts/deploy_on_server_with_ssh.sh

# deploy directly on the server
./scripts/deploy_production.sh

# manual backup
./scripts/backup.sh

# restore the newest backup (data only)
./scripts/restore.sh
# restore a specific backup (data only)
./scripts/restore.sh 2026-10-28_031500
# restore a backup together with the commit that went with it
./scripts/restore.sh --with-code [backup]
# undo the last deploy: previous commit + the backup taken just before it
./scripts/restore.sh --rollback

# help text
./scripts/restore.sh --help
```

`--yes` skips the confirmation question in `restore.sh`.

---

## What each script does

### `deploy_on_server_with_ssh.sh`

A one-line wrapper: `ssh host "cd <app dir> && ./scripts/deploy_production.sh"`. The host defaults to `opensillybytes.local` and can be overridden with `DEPLOY_HOST`. The app directory is set at the top of the file.

It exists so all deploy logic lives in one place (`deploy_production.sh`) and the same deploy can also be started directly on the server.

### `deploy_production.sh`

Steps, in order. Any failure stops the deploy (`set -euo pipefail`).

1. Remember the commit that is currently checked out (`prev`).
2. `git fetch origin main` and `git merge --ff-only origin/main`.
3. `docker compose build web`.
4. Run `backup.sh`.
5. `python manage.py migrate --noinput` in a fresh `web` container.
6. `docker compose up -d web`.
7. On exit (success or failure after the backup), append one line to the logs.

It refuses to run when `COMPOSE_FILE` points at a dev file (see [Safety guards](#safety-guards)).

### `backup.sh`

Creates `$BACKUP_DIR/YYYY-MM-DD_HHMMSS/` containing:

- `db.dump`: `pg_dump -Fc` of the database (compressed, restorable with `pg_restore`)
- `media.tar.gz`: the uploaded media
- `env.backup`: a copy of `.env`, because secrets are not in git

Then it verifies the dump can be read, appends a log line, deletes backups older than `KEEP_DAYS`, removes log entries for backups that no longer exist, and optionally copies everything off-site.

Settings (environment, then `.env`, then default):

| Setting | Default | Meaning |
| --- | --- | --- |
| `POSTGRES_DB` / `POSTGRES_USER` | `familienfelsen` | Database to dump |
| `BACKUP_DIR` | `$HOME/gr8base-backups` | Where backups and `deploy.log` go |
| `KEEP_DAYS` | `14` | Local retention |
| `MEDIA_DIR` | `data/media` | Media to archive |
| `BACKUP_REMOTE` | empty | Off-site target: `user@host:/path` (rsync) or `rclone:remote:bucket/path` |
| `BACKUP_HEARTBEAT_URL` | empty | Ping URL (e.g. healthchecks.io), requested only after a fully successful run |

Without `BACKUP_REMOTE` the script prints a warning: a backup on the same machine does not survive losing the server.

With `BACKUP_HEARTBEAT_URL` set, a monitoring service can alert you when a backup fails or does not run at all (cron or server down). Create a check with a 1-day period and a grace of a couple of hours. `deploy_production.sh` runs `backup.sh` too, so deploys also send a ping.

Cron example (daily at 03:15):

```
15 3 * * * /path/to/gr8base-community/scripts/backup.sh > /dev/null
```

Progress output is discarded; errors and warnings (stderr) still reach cron's own mail/syslog. The only log kept is `gr8base-backup.log` (see above).

### `restore.sh`

Always does the following, whatever the mode:

1. Resolve the backup and check that `db.dump` and `media.tar.gz` exist and are readable.
2. Ask for confirmation (unless `--yes`).
3. Save the current database and media to `$BACKUP_DIR/pre-restore_<timestamp>/`, so a wrong restore can be undone. These are pruned after `KEEP_DAYS`.
4. Stop `web`, drop and recreate the database, `pg_restore`, replace the media contents.
5. Run `migrate` (migrations newer than the backup are applied) and start `web`.

`env.backup` is **not** restored automatically. It holds secrets and may differ from the current `.env`. Copy it by hand if you are rebuilding a server.

Three modes decide which backup is used and whether the code changes:

| Mode | Backup used | Code |
| --- | --- | --- |
| *(none)* | newest, or the one you name | unchanged |
| `--with-code [backup]` | newest, or the one you name | reset to the commit logged for that backup |
| `--rollback` | the one from the newest deploy line | reset to that deploy's `prev=` commit |

For `--with-code` and `--rollback` the script also does `git reset --hard <commit>` and `docker compose build web` **before** stopping `web`, so the slow build adds no downtime. Afterwards a `restore` or `rollback` line is added to the logs.

---

## The logs

Two files get the same lines:

- `$BACKUP_DIR/deploy.log`: next to the backups, outside the repo. This is the one `restore.sh` reads.
- `gr8base-backup.log` in the project root: a convenience copy. Deleting it does not affect restores. It is untracked in git; add it to `.gitignore` if you want a clean `git status` on the server.

Line formats:

```
# a deploy
2026-10-29T20:46:10+0000 ok prev=a827d4e… new=a827d4e… backup=/srv/…/gr8base-backups/2026-10-29_204551
2026-10-29T21:02:44+0000 FAILED(1) prev=a827d4e… new=9f3c1b2… backup=/srv/…/2026-10-29_210230

# a backup outside a deploy (cron or manual)
2026-10-30T03:15:02+0000 backup commit=a827d4e… backup=/srv/…/gr8base-backups/2026-10-30_031500

# restores that changed code
2026-10-30T09:12:00+0000 rollback from=9f3c1b2… to=a827d4e… backup=/srv/…/2026-10-29_210230
2026-10-30T09:40:00+0000 restore  from=9f3c1b2… to=a827d4e… backup=/srv/…/2026-10-29_210230
```

How to read them:

- `prev` is the commit that was running before the deploy, `new` the one checked out after it. They are equal when there was nothing to pull.
- `FAILED(n)` means the deploy script exited with code `n` after the backup was taken. The merge may already have happened, so `new` shows what was checked out at that moment.
- `commit=` in a `backup` line is whatever was checked out when the backup ran. It tells you which code the backup belongs to, not that the app was healthy. To judge whether a commit worked, look at the `ok` and `FAILED` lines around it.

Entries whose backup directory no longer exists are removed by `backup.sh` after it prunes old backups. Lines without a `backup=` are kept.

---

## Why it is designed this way

**One deploy script, on the server.** The ssh wrapper only forwards. The logic runs the same whether started remotely or on the server, and there is no shell-escaping through ssh. The body of `deploy_production.sh` sits inside a function so bash has read all of it before `git merge` replaces the file.

**`--ff-only` merge.** The server should only follow origin. If it has diverged, something unexpected happened (for example an edit made on the server). The deploy then stops before the backup, migration or restart instead of creating a merge commit nobody reviewed.

**Backup right before `migrate`, not at the start.** The build can take a while. Taking the backup just before the schema changes means it holds the data exactly as the old code left it. That is also why a deploy line's backup belongs to its `prev` commit, not its `new` one. Migrations are the dangerous part of a deploy and are not reversible in general, so the backup is the rollback path.

**A failed backup aborts the deploy.** `backup.sh` exits non-zero on an empty or unreadable dump, and the deploy has `set -e`, so a deploy never reaches `migrate` without a good backup.

**The log ties commit and backup together.** A backup alone restores data into code that may not match it, and a commit alone says nothing about the data. Logging the pair is what makes `--rollback` and `--with-code` possible. The log sits next to the backups and not in the repo, so `git reset --hard` cannot touch it and the backup pruning (which only removes directories) leaves it alone.

**The trap writes the log on failure too.** The cases where you most need to know which backup goes with which commit are the failed ones: a failed migration or a failed restart after the migration ran.

**`restore.sh` saves the current state first.** Restoring replaces the database. The `pre-restore_*` copy means a restore started by mistake, or from the wrong backup, can itself be undone.

**Code reset and rebuild before stopping `web`.** The image must match the restored code, or the `migrate` at the end of the restore would re-apply the newer migrations to the old data. Doing the build first keeps the downtime to the actual database swap.

**Plain `restore.sh` leaves code alone.** Restoring data is the common, low-risk case, and `git reset --hard` is destructive on the server's checkout. Code changes only happen when you ask for them with `--with-code` or `--rollback`.

**Settings from the environment, then `.env`, then defaults.** `.env` is not `source`d. It is docker-style and may have inline comments bash cannot parse, so a small `grep`-based reader extracts single values. Keep values plain: no quotes, no trailing comments.

---

## Safety guards

- **Dev guard.** `deploy_production.sh`, `restore.sh --rollback` and `restore.sh --with-code` refuse to run when `COMPOSE_FILE` (environment or `.env`) contains `dev`. They run `git reset --hard` or pull `main`, which would destroy your own branch and uncommitted work in a development checkout. Override with `ALLOW_DEV_DEPLOY=1`, for example in a scratch clone used for testing. A plain `restore.sh` into the dev database is still allowed.
- **Confirmation.** `restore.sh` shows the backup, and for code modes the commit it will reset to, and asks before changing anything.
- **Checks before changes.** The restore refuses if the backup is missing or unreadable, if its log entry is missing, or if the commit is not in the local repository.
- **Backups are private.** `backup.sh` sets `umask 077` because the files contain user data and secrets.

---

## Typical situations

**A deploy went wrong after the migration ran**
1. Fix or revert the bad commit on origin, otherwise the next deploy brings it straight back.
2. `./scripts/restore.sh --rollback`. Check the printed log line and its timestamp before confirming.

**Go back to a specific day**
1. Find the backup in `deploy.log`, or list `$BACKUP_DIR`.
2. `./scripts/restore.sh --with-code 2026-10-28_031500`.

**Only the data is damaged, the code is fine**
`./scripts/restore.sh 2026-10-28_031500` (no code change).

**Rebuilding a new server**
Clone the repo, copy `env.backup` from the backup to `.env` by hand, start the `db` container, run `./scripts/restore.sh <backup dir>`.

**A restore went wrong**
`$BACKUP_DIR/pre-restore_<timestamp>/` holds the state from just before it. Restore from that directory with `./scripts/restore.sh /path/to/pre-restore_<timestamp>`.

---

## Limits to know about

- **Data written between the backup and a rollback is lost.** The `pre-restore_*` copy keeps it for `KEEP_DAYS`.
- **Destructive migrations cause a short outage.** `migrate` runs while the old container is still serving. A dropped or renamed column breaks old-code requests until `up -d web` swaps the container. For such changes, deploy in two steps: first code that no longer uses the column, then the migration that drops it.
- **Every deploy archives all media**, so deploys slow down as `MEDIA_DIR` grows.
- **A pruned newest deploy entry shifts `--rollback` further back.** When the backup of the newest deploy line has aged out, its line is removed and `--rollback` picks the next older deploy whose backup still exists. It prints that line and asks first, so check the timestamp.
- **Off-site copy is optional.** Without `BACKUP_REMOTE`, everything is on the server (even if on a different disk than the app).
- **The log shows what was checked out, not whether the app was healthy.** There is no automatic health check after `up -d web`.
