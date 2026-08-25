# Noticed

- [cleanup] user/default/workflows/__MACOSX, user/default/workflows/Wan/__MACOSX, user/default/workflows/old/wan/__MACOSX: AppleDouble junk (`._*.json`) from a Mac-made zip; 11 unparseable stub files (2026-08-25 workflow audit).
- [stale-file] "New folder/" untracked at repo root, contents unknown; predates the 2026-08-25 workflow-audit session.
- [cleanup] owner workflow saves scattered outside the library: input/ (20), input-mov/ (15), user/ top level (3), Downloads (1), Documents/RPG-Visual Design (1) — all indexed by the workflow-library tooling on branch claude/workflow-addons-research-h8v30e.
- [stale-file] user/FLUX9B - Flash Kitchen 80s.json: corrupt JSON (invalid at char 0); the "(1)" copy beside it parses fine.
- [dependency] comfyui-adaptiveprompts upstream py/generator.py emits SyntaxWarning (invalid escape "\_") on import; cosmetic, upstream defect.
- [cleanup] fork github.com/ArchonVII/ComfyUI carries ~250 mirrored upstream dev branches (alexis/*, matt/*, release/*, ...); consider pruning to master + active lanes (2026-08-25 consolidation).
