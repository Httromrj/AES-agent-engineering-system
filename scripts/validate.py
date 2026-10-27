from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
required = [
    "README.md", "VERSION", "core/engineering-charter.md", "core/workflow.md",
    "core/product-quality.md", "core/verification.md", "core/continuous-improvement.md",
    "skills/product-engineering/SKILL.md", "skills/codebase-investigation/SKILL.md",
    "skills/architecture-review/SKILL.md", "skills/implementation-quality/SKILL.md",
    "skills/continuous-improvement/SKILL.md", "evals/benchmark-tasks.md",
    "research/README.md", "research/sources.json", "research/gateway.example.json",
    "research/model-gateway-evaluation-2026-10-27.md", "deployment/README.md",
    "scripts/vps_preflight.py", "scripts/dashboard.py", "scripts/dashboard.html", "scripts/dashboard_login.html", "scripts/dashboard_auth.py", "scripts/test_dashboard_auth.py", "scripts/adopt.py", "scripts/test_adopt.py", "scripts/translate.py", "scripts/test_translate.py", "scripts/innovation.py", "scripts/test_innovation.py",
    "scripts/gateway.py", "scripts/test_gateway.py",
    "scripts/install.py", "scripts/test_install.py"
]
errors = [f"Missing required file: {p}" for p in required if not (ROOT / p).is_file()]
for rel in required:
    p = ROOT / rel
    if p.is_file() and rel.endswith("SKILL.md"):
        data = p.read_text(encoding="utf-8")
        if not data.startswith("---\n") or "\nname:" not in data or "\ndescription:" not in data:
            errors.append(f"Invalid skill frontmatter: {rel}")
if errors:
    print("VALIDATION FAILED\n" + "\n".join(f"- {e}" for e in errors))
    sys.exit(1)
print(f"Validation passed: {len(required)} required files present.")
