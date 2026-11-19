import argparse
import os
import pathlib
import re
import subprocess
import sys

SECRETS = [
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("AWS key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})"),
    ("Anthropic key", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("OpenAI key", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    ("Google key", r"\bAIza[0-9A-Za-z_-]{35}"),
    ("Slack token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    ("Stripe key", r"\b[rs]k_live_[A-Za-z0-9]{20,}"),
    ("JWT", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    (
        "connection string secret",
        r"(?i)\b(?:AccountKey|SharedAccessKey|Password|Pwd)=[^;\s'\"]{6,}",
    ),
    (
        "assigned secret",
        r"(?i)\b[\w-]*(?:api[_-]?key|secret|token|passw(?:or)?d)[\w-]*['\"]?\s*[:=]\s*['\"][^'\"\s]{8,}['\"]",
    ),
    ("credentials in URL", r"\b[a-z][a-z0-9+.-]*://[^/\s:@'\"]+:[^/\s@'\"]+@"),
]
SECRETS = [(k, re.compile(p)) for k, p in SECRETS]

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
SAFE_EMAIL_DOMAINS = (
    "users.noreply.github.com",
    "noreply.github.com",
    "example.com",
    "example.org",
    "example.net",
)
SAFE_EMAILS = {"git@github.com"}
HOME_PATH = re.compile(
    r"(?i)(?:\b[A-Z]:[\\/]+Users[\\/]+|/home/|/Users/)(?!(?:Public|Default|runneradmin)\b)[^\\/\s'\"<>]+"  # publish: allow
)
SENSITIVE_NAME = re.compile(
    r"(?i)(?:^\.env(?:\..*)?$|\.(?:pem|key|pfx|p12|jks|kdbx|keystore|ini|db|sqlite3?)$|^id_(?:rsa|dsa|ecdsa|ed25519)|^credentials|^secrets?\b|\.netrc$|\.npmrc$|\.pypirc$)"
)
ALLOW_MARK = "publish: allow"


def identity_terms(extra=()):
    found = []
    for var in ("USERNAME", "COMPUTERNAME", "USERDOMAIN"):
        v = os.environ.get(var, "")
        if v and v.upper() != "WORKGROUP":
            found.append(v)
    for key in ("user.name", "user.email"):
        r = subprocess.run(
            ["git", "config", "--get", key], capture_output=True, text=True
        )
        v = r.stdout.strip()
        if v and not v.lower().endswith(SAFE_EMAIL_DOMAINS):
            found.append(v)
            if "@" in v:
                found.append(v.split("@")[0])
    found.extend(extra)
    out = []
    for t in found:
        t = t.strip()
        if len(t) >= 3 and t.lower() not in (x.lower() for x in out):
            out.append(t)
    return out


def denylist():
    p = pathlib.Path(os.environ["USERPROFILE"]) / ".claude" / "publish_denylist.txt"
    if not p.is_file():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    return [x.strip() for x in lines if x.strip() and not x.lstrip().startswith("#")]


def _term_rx(terms):
    if not terms:
        return None
    alt = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?i)(?<![A-Za-z0-9]){alt}(?![A-Za-z0-9])")


def _mask(s):
    return s if len(s) <= 8 else s[:4] + "..." + s[-2:]


def scan_text(text, terms, allowed=()):
    term_rx = _term_rx(terms)
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARK in line:
            continue
        for kind, rx in SECRETS:
            for m in rx.finditer(line):
                hits.append((n, kind, _mask(m.group(0))))
        clean = line
        for a in allowed:
            clean = re.sub(re.escape(a), " ", clean, flags=re.I)
        for m in EMAIL.finditer(clean):
            e = m.group(0).lower()
            local, domain = e.split("@", 1)
            if e in SAFE_EMAILS or domain.endswith(SAFE_EMAIL_DOMAINS):
                continue
            if local in ("noreply", "no-reply"):
                continue
            hits.append((n, "email", m.group(0)))
        for m in HOME_PATH.finditer(clean):
            hits.append((n, "user home path", m.group(0)))
        if term_rx:
            for m in term_rx.finditer(clean):
                hits.append((n, "identity term", m.group(0)))
    return hits


def is_sensitive_name(path):
    return bool(SENSITIVE_NAME.search(pathlib.PurePath(path).name))


def is_binary(data):
    return b"\0" in data[:8192]


def git(root, *args, data=None):
    r = subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=False
    )
    if r.returncode != 0:
        sys.exit(
            f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace').strip()}"
        )
    return r.stdout


def push_files(root):
    out = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted({p for p in out.decode().split("\0") if p})


def tracked_ignored(root):
    out = git(root, "ls-files", "-z", "--cached", "--ignored", "--exclude-standard")
    return sorted(p for p in out.decode().split("\0") if p)


def has_remote(root):
    return bool(git(root, "remote").strip())


def unpushed_range(root):
    return ["--all", "--not", "--remotes"] if has_remote(root) else ["--all"]


def history_blobs(root):
    # every blob reachable from local refs and not already on a remote
    lines = (
        git(root, "rev-list", "--objects", *unpushed_range(root)).decode().splitlines()
    )
    paths = {}
    for ln in lines:
        sha, _, path = ln.partition(" ")
        if path:
            paths.setdefault(sha, path)
    if not paths:
        return
    buf = git(root, "cat-file", "--batch", data=("\n".join(paths) + "\n").encode())
    i = 0
    while i < len(buf):
        nl = buf.index(b"\n", i)
        head = buf[i:nl].split()
        if head[1] == b"missing":
            i = nl + 1
            continue
        size = int(head[2])
        body = buf[nl + 1 : nl + 1 + size]
        i = nl + 2 + size
        if head[1] == b"blob":
            yield head[0].decode(), paths[head[0].decode()], body


def history_commits(root):
    fmt = "%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x1e"
    out = git(root, "rev-list", f"--format={fmt}", *unpushed_range(root)).decode(
        errors="replace"
    )
    for rec in out.split("\x1e"):
        rec = rec.split("\n", 1)[-1] if rec.lstrip().startswith("commit ") else rec
        parts = rec.strip("\n").split("\0")
        if len(parts) == 6:
            yield parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--history", action="store_true")
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    allowed = [a.repo, f"{a.repo}.git"]
    terms = identity_terms(denylist())
    problems = []

    for p in push_files(root):
        f = root / p
        if not f.is_file():
            continue
        if is_sensitive_name(p):
            problems.append(f"{p}: sensitive file name")
        data = f.read_bytes()
        if is_binary(data):
            continue
        for n, kind, s in scan_text(
            data.decode("utf-8", errors="replace"), terms, allowed
        ):
            problems.append(f"{p}:{n}: {kind}: {s}")

    for p in tracked_ignored(root):
        problems.append(
            f"{p}: tracked but ignored, still pushed (untrack with git rm --cached)"
        )

    if a.history:
        current = {
            p: (root / p).read_bytes() for p in push_files(root) if (root / p).is_file()
        }
        for sha, p, body in history_blobs(root):
            if current.get(p) == body:
                continue
            if is_sensitive_name(p):
                problems.append(f"history {sha[:8]} {p}: sensitive file name")
            if is_binary(body):
                continue
            for n, kind, s in scan_text(
                body.decode("utf-8", errors="replace"), terms, allowed
            ):
                problems.append(f"history {sha[:8]} {p}:{n}: {kind}: {s}")
        for h, an, ae, cn, ce, msg in history_commits(root):
            for e in {ae, ce}:
                if not e.lower().endswith(SAFE_EMAIL_DOMAINS):
                    problems.append(f"commit {h[:8]}: author/committer email {e}")
            for n, kind, s in scan_text(msg, terms, allowed):
                problems.append(f"commit {h[:8]} message:{n}: {kind}: {s}")

    if problems:
        print("\n".join(dict.fromkeys(problems)))
        sys.exit(
            f"{len(problems)} problem(s); fix, or mark a reviewed line with '{ALLOW_MARK}'"
        )
    print(
        f"clean: {len(push_files(root))} files"
        + (", unpushed history" if a.history else "")
    )


if __name__ == "__main__":
    main()
