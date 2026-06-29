"""Slot/field definitions for the Prompt Composer nodes.

This is the single source of truth for the slot-based nodes (Clothing, Body,
Environment).  Both ``nodes.py`` (to build INPUT_TYPES) and ``store.py`` (to
expose a schema route the JS frontend reads) import from here, so the Python
widgets and the frontend preset UI can never drift apart.

Each slot is ``(key, label)``:
  * ``key``   -> the ComfyUI widget name (also the JSON output key)
  * ``label`` -> human-friendly text the frontend shows in tooltips/headers
"""

# --- Clothing -------------------------------------------------------------
# Ordered roughly head -> torso -> legs -> feet so the assembled string reads
# top-to-bottom, which is how a person is usually described.  Order is a design
# choice, not a hard rule.
CLOTHING_SLOTS = [
    ("headwear", "Headwear (hat, cap, hood)"),
    ("face_eyewear", "Face / eyewear (glasses, mask)"),
    ("top", "Top (shirt, blouse, t-shirt)"),
    ("outerwear", "Outerwear (jacket, coat)"),
    ("full_outfit", "Full outfit (dress, suit, uniform)"),
    ("bottom", "Bottom (pants, skirt, shorts)"),
    ("hosiery", "Hosiery / legs (stockings, tights)"),
    ("footwear", "Footwear (shoes, boots)"),
    ("gloves_accessories", "Gloves / accessories (jewelry, bag)"),
    ("underwear", "Underwear / lingerie"),
    ("extra", "Extra (free-form clothing detail)"),
]

# When the "nude" toggle is on, these garment slots are suppressed but the
# accessory slots (everything NOT listed here) are kept -- "nude but still
# wearing a hat / glasses / socks" is an extremely common real request, so a
# blanket wipe would be the wrong default.  Suppression set per user intent
# "toggle for just nude".
CLOTHING_GARMENT_KEYS = {
    "top",
    "outerwear",
    "full_outfit",
    "bottom",
    "hosiery",
    "footwear",
    "underwear",
}

# --- Body / subject description ------------------------------------------
BODY_SLOTS = [
    ("subject", "Subject (e.g. 'young woman, 25yo')"),
    ("body_type", "Body type / shape"),
    ("height_build", "Height & build"),
    ("skin", "Skin (tone, texture)"),
    ("hair", "Hair (style, color, length)"),
    ("eyes", "Eyes (color, shape)"),
    ("face", "Facial features"),
    ("expression", "Expression / emotion"),
    ("chest", "Chest / bust"),
    ("features", "Distinguishing features (tattoos, scars)"),
    ("pose", "Pose / gesture"),
]

# --- Environment / scene --------------------------------------------------
ENV_SLOTS = [
    ("location", "Location (where)"),
    ("setting", "Setting details"),
    ("background", "Background elements"),
    ("time_of_day", "Time of day"),
    ("season", "Season"),
    ("weather", "Weather"),
    ("lighting", "Lighting"),
    ("atmosphere", "Mood / atmosphere"),
    ("palette", "Color palette"),
    ("shot", "Shot / camera angle"),
]

# Node id -> {category, slots}.  ``category`` is also the key presets are
# filed under in the data store, so a Clothing preset and a Body preset of the
# same name don't collide.
NODE_SLOTS = {
    "PromptComposerClothing": {"category": "clothing", "slots": CLOTHING_SLOTS},
    "PromptComposerBody": {"category": "body", "slots": BODY_SLOTS},
    "PromptComposerEnvironment": {"category": "environment", "slots": ENV_SLOTS},
}


def schema_payload():
    """JSON-serialisable copy for the /schema route consumed by the frontend."""
    return {
        node_id: {
            "category": info["category"],
            "slots": [{"key": k, "label": lbl} for k, lbl in info["slots"]],
            "garment_keys": sorted(CLOTHING_GARMENT_KEYS)
            if info["category"] == "clothing"
            else [],
        }
        for node_id, info in NODE_SLOTS.items()
    }
