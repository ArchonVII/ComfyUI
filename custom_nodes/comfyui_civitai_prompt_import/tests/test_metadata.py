from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest


PACKAGE_DIR = os.path.dirname(os.path.dirname(__file__))
CUSTOM_NODES_DIR = os.path.dirname(PACKAGE_DIR)
if CUSTOM_NODES_DIR not in sys.path:
    sys.path.insert(0, CUSTOM_NODES_DIR)

from comfyui_civitai_prompt_import.metadata import (  # noqa: E402
    build_report_from_generation_text,
    build_report_from_page_json,
    extract_image_id_from_civitai_url,
)


class CivitaiMetadataTests(unittest.TestCase):
    def test_extracts_image_id_from_page_and_query_urls(self):
        self.assertEqual(
            extract_image_id_from_civitai_url("https://civitai.red/images/12097475?foo=bar"),
            12097475,
        )
        self.assertEqual(
            extract_image_id_from_civitai_url("https://civitai.com/posts/2669960?imageId=12097475"),
            12097475,
        )

    def test_builds_report_from_nested_page_json(self):
        page_json = {
            "props": {
                "pageProps": {
                    "trpcState": {
                        "json": {
                            "queries": [
                                {
                                    "state": {
                                        "data": {
                                            "id": 12097475,
                                            "meta": {
                                                "prompt": "score_9, forest, <lora:pony/kenva:0.8>",
                                                "negativePrompt": "score_6, blurry",
                                                "cfgScale": 7,
                                                "steps": 25,
                                                "sampler": "Euler a Karras",
                                                "seed": 3269595310,
                                                "hashes": {
                                                    "model": "67ab2fd8ec",
                                                    "LORA:pony/kenva": "189804f733",
                                                },
                                            },
                                            "resources": [
                                                {
                                                    "imageId": 12097475,
                                                    "modelVersionId": 290640,
                                                    "modelId": 257749,
                                                    "modelName": "Pony Diffusion V6 XL",
                                                    "modelType": "Checkpoint",
                                                    "versionName": "V6",
                                                    "baseModel": "Pony",
                                                },
                                                {
                                                    "imageId": 12097475,
                                                    "modelVersionId": 330475,
                                                    "modelId": 264290,
                                                    "modelName": "Not Artists Styles",
                                                    "modelType": "LORA",
                                                    "versionName": "v1",
                                                    "strength": 0.8,
                                                },
                                            ],
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }

        report = build_report_from_page_json(
            "https://civitai.red/images/12097475",
            page_json,
            [],
            image_id=12097475,
        )

        self.assertEqual(report.prompt, "score_9, forest, <lora:pony/kenva:0.8>")
        self.assertEqual(report.negative_prompt, "score_6, blurry")
        self.assertTrue(any(item.key == "Steps" and item.value == "25" for item in report.settings))
        self.assertTrue(any(item.key == "Sampler" and item.value == "Euler a Karras" for item in report.settings))
        self.assertEqual(len(report.resources), 2)
        self.assertEqual(report.resources[0].availability, "unchecked")

    def test_parses_a1111_generation_text(self):
        report = build_report_from_generation_text(
            "https://image.civitai.com/example.jpeg",
            "a cat in a window\n"
            "Negative prompt: blurry, low quality\n"
            "Steps: 30, Sampler: DPM++ 2M Karras, CFG scale: 7, Seed: 1234, Size: 512x768, Model: ponyDiffusionV6XL",
            [],
        )

        self.assertEqual(report.prompt, "a cat in a window")
        self.assertEqual(report.negative_prompt, "blurry, low quality")
        self.assertTrue(any(item.key == "CFG scale" and item.value == "7" for item in report.settings))
        self.assertTrue(any(item.key == "Model" and item.value == "ponyDiffusionV6XL" for item in report.settings))

    def test_marks_local_model_as_found_by_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = os.path.join(temp_dir, "ponyDiffusionV6XL.safetensors")
            with open(model_path, "wb") as handle:
                handle.write(b"placeholder")

            report = build_report_from_page_json(
                "https://civitai.red/images/1",
                {
                    "id": 1,
                    "meta": {"prompt": "pony portrait", "Model": "ponyDiffusionV6XL"},
                },
                [temp_dir],
                image_id=1,
            )

            self.assertEqual(report.resources[0].availability, "found")
            self.assertEqual(report.resources[0].matched_path, model_path)

    def test_report_serializes_to_json_shape(self):
        report = build_report_from_generation_text(
            "https://image.civitai.com/example.jpeg",
            "prompt\nSteps: 1, Seed: 2",
            [],
        )
        encoded = json.dumps(report.to_dict())
        self.assertIn("source_url", encoded)
        self.assertIn("settings", encoded)


if __name__ == "__main__":
    unittest.main()
