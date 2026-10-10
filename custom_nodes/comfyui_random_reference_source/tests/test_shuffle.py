from pathlib import Path

from custom_nodes.comfyui_random_reference_source.nodes import choose_image, build_reference_preview_payload


def test_shuffle_visits_every_file_each_cycle_and_replays():
    pool = [Path(f'{i}.png') for i in range(11)]
    sequence = [choose_image(pool, i, 'shuffle_cycle') for i in range(1, 34)]
    for start in range(0, 33, 11):
        assert set(sequence[start:start + 11]) == set(pool)
    assert sequence == [choose_image(pool, i, 'shuffle_cycle') for i in range(1, 34)]
    assert sequence[:11] != sequence[11:22]
    assert choose_image(pool[:1], 19, 'shuffle_cycle') == pool[0]


def test_shuffle_preview_predicts_actual_selection(tmp_path):
    from PIL import Image
    for i in range(4):
        Image.new('RGB', (2, 2)).save(tmp_path / f'{i}.png')
    result = build_reference_preview_payload('folder', str(tmp_path), 'None', '', 'shuffle_cycle', 7, False)
    assert result['preview_is_exact_next'] is True
    assert result['images'][0]['path'] == str(choose_image(sorted(tmp_path.iterdir()), 7, 'shuffle_cycle'))
