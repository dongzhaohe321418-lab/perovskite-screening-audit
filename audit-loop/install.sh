#!/bin/bash
# audit-loop installer — generates every machine-specific file from templates so a
# fresh clone reproduces the whole workflow. Idempotent.
#
#   ./install.sh [--science-repo PATH] [--audit-repo PATH] [--controller PATH]
#                [--project-id ID] [--science-branch B] [--audit-branch B]
#                [--science-full-name owner/repo] [--audit-full-name owner/repo]
#                [--label com.example.audit-loop] [--no-launchd] [--no-hook]
#
# Defaults assume the sibling layout this repository was developed in:
#   <parent>/scienceRepo  <parent>/auditRepo  <parent>/science-audit-controller
#
# Writes ONLY:
#   audit-loop/state/**                          (dirs, secrets, generated config)
#   audit-loop/orchestrator/{config,projects}.yaml
#   <science repo>/.git/hooks/post-commit        (git plumbing, never repo content)
#   ~/Library/LaunchAgents/<label>.plist
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PARENT="$(dirname "$ROOT")"

SCIENCE_REPO="$PARENT/scienceRepo"
AUDIT_REPO="$PARENT/auditRepo"
CONTROLLER_ROOT="$PARENT/science-audit-controller"
PROJECT_ID="perovskite-screening"
SCIENCE_BRANCH="main"
AUDIT_BRANCH="audit"
SCIENCE_FULL_NAME=""
AUDIT_FULL_NAME=""
LABEL="com.$(id -un).audit-loop"
DO_LAUNCHD=1
DO_HOOK=1

while [ $# -gt 0 ]; do
  case "$1" in
    --science-repo) SCIENCE_REPO="$2"; shift 2;;
    --audit-repo) AUDIT_REPO="$2"; shift 2;;
    --controller) CONTROLLER_ROOT="$2"; shift 2;;
    --project-id) PROJECT_ID="$2"; shift 2;;
    --science-branch) SCIENCE_BRANCH="$2"; shift 2;;
    --audit-branch) AUDIT_BRANCH="$2"; shift 2;;
    --science-full-name) SCIENCE_FULL_NAME="$2"; shift 2;;
    --audit-full-name) AUDIT_FULL_NAME="$2"; shift 2;;
    --label) LABEL="$2"; shift 2;;
    --no-launchd) DO_LAUNCHD=0; shift;;
    --no-hook) DO_HOOK=0; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

die() { echo "install.sh: $*" >&2; exit 1; }

for d in "$SCIENCE_REPO" "$AUDIT_REPO" "$CONTROLLER_ROOT"; do
  [ -d "$d" ] || die "not found: $d (pass the right --flag)"
done
git -C "$SCIENCE_REPO" rev-parse --git-dir >/dev/null 2>&1 || die "$SCIENCE_REPO is not a git repo"
git -C "$AUDIT_REPO" rev-parse --git-dir >/dev/null 2>&1 || die "$AUDIT_REPO is not a git repo"
[ -f "$CONTROLLER_ROOT/app/main.py" ] || die "$CONTROLLER_ROOT does not look like science-audit-controller"

# Resolve to absolute, symlink-free paths so generated files are unambiguous.
SCIENCE_REPO="$(cd "$SCIENCE_REPO" && pwd -P)"
AUDIT_REPO="$(cd "$AUDIT_REPO" && pwd -P)"
CONTROLLER_ROOT="$(cd "$CONTROLLER_ROOT" && pwd -P)"

derive_full_name() {  # owner/repo from a git remote, else <fallback>
  local repo="$1" fallback="$2" url
  url="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
  if [ -n "$url" ]; then
    # strip trailing .git, then keep the last two path segments (owner/repo)
    url="${url%.git}"
    url="${url%/}"
    # Separate statements: within one `local`, later RHS cannot see earlier names.
    local name owner_part owner
    name="${url##*/}"
    owner_part="${url%/*}"
    owner="${owner_part##*[:/]}"
    if [ -n "$owner" ] && [ -n "$name" ] && [ "$owner" != "$name" ]; then
      echo "$owner/$name"
    else
      echo "$fallback"
    fi
  else
    echo "$fallback"
  fi
}
[ -n "$SCIENCE_FULL_NAME" ] || SCIENCE_FULL_NAME="$(derive_full_name "$SCIENCE_REPO" "local/$(basename "$SCIENCE_REPO")")"
[ -n "$AUDIT_FULL_NAME" ] || AUDIT_FULL_NAME="$(derive_full_name "$AUDIT_REPO" "local/$(basename "$AUDIT_REPO")")"

CODEX="$(command -v codex || true)"
[ -n "$CODEX" ] || { CODEX="codex"; echo "warning: codex not on PATH; config will say 'codex'"; }

AUDIT_HEAD="$(git -C "$AUDIT_REPO" rev-parse "refs/heads/$AUDIT_BRANCH" 2>/dev/null || true)"
[ -n "$AUDIT_HEAD" ] || die "audit repo has no branch '$AUDIT_BRANCH'"

echo "== audit-loop install =="
echo "   root        $ROOT"
echo "   science     $SCIENCE_REPO  ($SCIENCE_FULL_NAME, branch $SCIENCE_BRANCH)"
echo "   audit       $AUDIT_REPO  ($AUDIT_FULL_NAME, branch $AUDIT_BRANCH @ ${AUDIT_HEAD:0:12})"
echo "   controller  $CONTROLLER_ROOT"
echo "   codex       $CODEX"

mkdir -p "$ROOT/state"/{spool,spool/processed,cycles,worktrees,pending_reviews,pending_reviews/recorded,logs,controller}

# 1. virtualenv
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "-- creating virtualenv"
  "${PYTHON:-python3}" -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/pip" -q install -e "$CONTROLLER_ROOT[test]" pyyaml
echo "-- venv ready: $("$ROOT/.venv/bin/python" --version)"

# 2. secrets (generated once, 600)
SECRETS="$ROOT/state/secrets.env"
if [ ! -f "$SECRETS" ]; then
  "$ROOT/.venv/bin/python" - "$SECRETS" <<'EOF'
import secrets, sys
keys = ["GITHUB_WEBHOOK_SECRET", "ACTION_API_TOKEN", "CLAUDE_API_TOKEN",
        "PI_APPROVAL_TOKEN", "CONTROLLER_READ_TOKEN"]
with open(sys.argv[1], "w") as fh:
    for key in keys:
        fh.write(f"{key}={secrets.token_hex(32)}\n")
EOF
  chmod 600 "$SECRETS"
  echo "-- generated $SECRETS"
else
  echo "-- secrets already present"
fi

# 3. generated config from templates
render() {  # render <template> <destination>
  sed -e "s#__ROOT__#$ROOT#g" \
      -e "s#__SCIENCE_REPO__#$SCIENCE_REPO#g" \
      -e "s#__AUDIT_REPO__#$AUDIT_REPO#g" \
      -e "s#__CONTROLLER_ROOT__#$CONTROLLER_ROOT#g" \
      -e "s#__PROJECT_ID__#$PROJECT_ID#g" \
      -e "s#__SCIENCE_BRANCH__#$SCIENCE_BRANCH#g" \
      -e "s#__AUDIT_BRANCH__#$AUDIT_BRANCH#g" \
      -e "s#__SCIENCE_FULL_NAME__#$SCIENCE_FULL_NAME#g" \
      -e "s#__AUDIT_FULL_NAME__#$AUDIT_FULL_NAME#g" \
      -e "s#__SCIENCE_NAME__#$(basename "$SCIENCE_REPO")#g" \
      -e "s#__AUDIT_NAME__#$(basename "$AUDIT_REPO")#g" \
      -e "s#__AUDIT_INITIAL_COMMIT__#$AUDIT_HEAD#g" \
      -e "s#__CODEX__#$CODEX#g" \
      -e "s#__SPOOL__#$ROOT/state/spool#g" \
      -e "s#__BRANCH__#$SCIENCE_BRANCH#g" \
      -e "s#__LABEL__#$LABEL#g" \
      -e "s#__PYTHON__#$ROOT/.venv/bin/python#g" \
      -e "s#__ORCHESTRATOR__#$ROOT/orchestrator/orchestrator.py#g" \
      -e "s#__PATH__#/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin#g" \
      -e "s#__HOME__#$HOME#g" \
      "$1" > "$2"
}

# projects.yaml pins the trusted audit root; never clobber it once the loop has run,
# or the controller would re-trust a head it never validated.
if [ -f "$ROOT/orchestrator/projects.yaml" ]; then
  echo "-- projects.yaml exists; leaving its trusted audit root untouched"
else
  render "$ROOT/orchestrator/projects.example.yaml" "$ROOT/orchestrator/projects.yaml"
  echo "-- generated orchestrator/projects.yaml"
fi
render "$ROOT/orchestrator/config.example.yaml" "$ROOT/orchestrator/config.yaml"
echo "-- generated orchestrator/config.yaml"

# 4. git hook (into .git/hooks: plumbing, never tracked repo content)
if [ "$DO_HOOK" = 1 ]; then
  HOOK_DST="$(git -C "$SCIENCE_REPO" rev-parse --absolute-git-dir)/hooks/post-commit"
  mkdir -p "$(dirname "$HOOK_DST")"
  render "$ROOT/hooks/post-commit.template" "$ROOT/state/post-commit.generated"
  if [ -f "$HOOK_DST" ] && ! cmp -s "$ROOT/state/post-commit.generated" "$HOOK_DST"; then
    cp "$HOOK_DST" "$HOOK_DST.backup.$(date +%s)"
    echo "-- backed up existing post-commit hook"
  fi
  cp "$ROOT/state/post-commit.generated" "$HOOK_DST"
  chmod +x "$HOOK_DST"
  echo "-- installed hook: $HOOK_DST"
fi

# 5. launchd agent
if [ "$DO_LAUNCHD" = 1 ]; then
  if [ "$(uname)" != "Darwin" ]; then
    echo "-- not macOS; skipping launchd. Run 'orchestrator.py process' from cron/systemd instead."
  else
    PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    render "$ROOT/launchd/agent.plist.template" "$PLIST_DST"
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
    echo "-- launchd agent loaded: $LABEL"
  fi
fi

echo
echo "== done =="
echo "   selftest:  $ROOT/.venv/bin/python $ROOT/selftest.py"
echo "   status:    tail -20 $ROOT/state/logs/launchd.out.log"
[ "$DO_LAUNCHD" = 1 ] && [ "$(uname)" = "Darwin" ] && \
  echo "   agent:     launchctl print gui/$(id -u)/$LABEL | head -20"
echo "   MCP:       register $ROOT/mcp/audit_mcp_server.py (see mcp/README_MCP.md)"
