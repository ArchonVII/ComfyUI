"""Standalone logic check (not loaded by ComfyUI). Run with the ComfyUI venv.

Loads the package without ComfyUI's `server` module present (routes are skipped
gracefully) and exercises every node's execute path.
"""
import importlib.util
import json
import os
import sys

PKG_DIR = os.path.dirname(os.path.realpath(__file__))
spec = importlib.util.spec_from_file_location(
    "pc", os.path.join(PKG_DIR, "__init__.py"), submodule_search_locations=[PKG_DIR]
)
pc = importlib.util.module_from_spec(spec)
sys.modules["pc"] = pc
spec.loader.exec_module(pc)

M = pc.NODE_CLASS_MAPPINGS
ok = True


def check(label, got, want):
    global ok
    status = "PASS" if got == want else "FAIL"
    if got != want:
        ok = False
    print(f"[{status}] {label}\n       got:  {got!r}\n       want: {want!r}")


# 1. Clothing: red baseball hat on head + blue shirt on torso (the user's example)
cloth = M["PromptComposerClothing"]()
prompt, pj = cloth.build(
    nude=False, nude_text="nude", separator=", ",
    headwear="red baseball hat", top="blue shirt",
)
check("clothing basic prompt", prompt, "red baseball hat, blue shirt")
check("clothing basic json", json.loads(pj), {"headwear": "red baseball hat", "top": "blue shirt"})

# 2. Clothing nude: garments dropped, accessories (hat) kept, nude leads
prompt2, pj2 = cloth.build(
    nude=True, nude_text="nude, naked", separator=", ",
    headwear="red baseball hat", top="blue shirt", footwear="sneakers",
)
check("clothing nude keeps accessory", prompt2, "nude, naked, red baseball hat")

# 3. Clothing chaining via prepend
prompt3, _ = cloth.build(
    nude=False, nude_text="nude", separator=", ",
    top="green hoodie", prepend="1girl, solo",
)
check("clothing prepend chain", prompt3, "1girl, solo, green hoodie")

# 4. Body
body = M["PromptComposerBody"]()
bp, bj = body.build(separator=", ", subject="young woman", hair="long red hair", eyes="green eyes")
check("body prompt", bp, "young woman, long red hair, green eyes")

# 5. Environment
env = M["PromptComposerEnvironment"]()
ep, _ = env.build(separator=", ", location="city street", lighting="golden hour")
check("environment prompt", ep, "city street, golden hour")

# 6. Snippets resolved from the shipped data store (library "quality")
snip = M["PromptComposerSnippets"]()
sp, sj = snip.build(library="quality", selected='["Photoreal", "Studio"]', separator=", ")
check(
    "snippets resolve from store", sp,
    "photorealistic, highly detailed, sharp focus, 8k, professional studio photograph, softbox lighting",
)

# 7. Snippets with a missing/garbage selection -> empty, no crash
sp2, _ = snip.build(library="quality", selected="not json", separator=", ")
check("snippets bad selection is safe", sp2, "")

# 8. Combine + dedupe
comb = M["PromptComposerCombine"]()
cp, = comb.build(separator=", ", dedupe=True, text_1="a, b", text_2="b", text_3="c")
check("combine dedupe", cp, "a, b, c")

print("\nDISPLAY NAMES:", pc.NODE_DISPLAY_NAME_MAPPINGS)
print("WEB_DIRECTORY:", pc.WEB_DIRECTORY)
print("\nRESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
