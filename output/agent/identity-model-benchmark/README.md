# Controlled Face-Swap Evidence

All people in this benchmark are synthetic and were generated specifically for this test.

## Preferred visual proof

- Identity source: `source_identity.png`
- Target scene: `target_scene_v2.png`
- Restored result: `reactor-gfpgan_00001_.png`
- Identity report: `user/default/identity_score_runs/20260726-170739-reactor-proof-gfpgan.json`

Restored-result measurements:

- OpenCV SFace cosine similarity: **0.780879**
- Configured same-identity threshold: **0.363**
- Same identity: **true**
- Result face-detection confidence: **0.892861**
- Restoration: GFPGAN v1.4 at 0.75 visibility

Visual inspection confirmed that the result carries the source portrait's angular face, strong brows, hazel eyes, narrow nose bridge, cheek structure, and smile while retaining the target's hair, clothing, framing, coffee-shop background, and lighting.

## Raw high-similarity proof

- Raw result: `reactor-baseline_00002_.png`
- Identity report: `user/default/identity_score_runs/20260726-170604-reactor-proof-baseline.json`
- OpenCV SFace cosine similarity: **0.812342**
- Same identity: **true**

This raw result scores higher but has visibly softer face texture and a more obvious pasted-face boundary than the restored result.

## Hard cross-sex stress case

- Alternate target: `target_scene.png`
- Result: `reactor-baseline_00001_.png`
- Identity report: `user/default/identity_score_runs/20260726-170340-reactor-proof-baseline.json`
- OpenCV SFace cosine similarity: **0.680509**
- Same identity: **true**

This intentionally difficult case proves that the source/target ordering works, but it is not the preferred visual demonstration.

## Reproduction

Editable workflow:

`user/default/workflows/agent/44 - Face Swap Proof and ReActor Baseline.json`

Executable API workflow:

`user/default/api_workflows/agent/44 - Face Swap Proof and ReActor Baseline API.json`

The API workflow defaults to the preferred same-gender pair and GFPGAN-restored configuration. ReActor is a labeled baseline only; it is not evidence of native Krea, FireRed, or Z-Image identity performance.
