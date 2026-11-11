import cv2
import numpy as np

from tennis_ai.ball_benchmark import predict, report, score


def make_game(root, game, labels):
    folder = root / f"game{game}" / "Clip1"
    folder.mkdir(parents=True)
    lines = ["file name,visibility,x-coordinate,y-coordinate,status"]
    for index, (visibility, x, y) in enumerate(labels):
        name = f"{index:04d}.jpg"
        cv2.imwrite(str(folder / name), np.zeros((720, 1280, 3), np.uint8))
        lines.append(f"{name},{visibility},{x},{y},{0 if visibility else ''}")
    (folder / "Label.csv").write_text("\n".join(lines) + "\n")


def test_public_ball_benchmark_counts_and_game_split(tmp_path):
    make_game(tmp_path, 1, [(1, 100, 100), (1, 110, 100), (0, "", ""), (2, 130, 100)])
    make_game(tmp_path, 9, [(1, 400, 300), (1, 410, 300)])
    answers = iter(
        [
            [(100, 100)],  # exact
            [(118, 100)],  # 8 px off: wrong at 5 px, right at 10 px
            [(125, 100)],  # ball absent: false positive
            [],  # visible but missed
            [(400, 303)],
            [(900, 600), (410, 300)],  # tracker keeps the candidate near the last point
        ]
    )

    def detect(_frame):
        return [
            {"box": [x - 3, y - 3, x + 3, y + 3], "confidence": 0.5 - 0.1 * i}
            for i, (x, y) in enumerate(next(answers))
        ]

    rows = list(predict(tmp_path, [1, 9], detect))
    assert [row["game"] for row in rows] == [1, 1, 1, 1, 9, 9]
    assert rows[2]["truth"] is None and rows[3]["status"] == "0"

    train = [row for row in rows if row["game"] == 1]
    strict, loose = score(train, 5), score(train, 10)
    assert (strict["tp"], strict["fp"], strict["fn"]) == (1, 2, 2)
    assert (loose["tp"], loose["fp"], loose["fn"]) == (2, 1, 1)
    assert loose["recall_by_visibility"]["2"] == {"hit": 0, "total": 1, "recall": 0.0}

    result = report(rows, "tracknet-v2")
    assert result["in_sample_warning"]
    test = result["results"]["5px"]["test"]
    assert (test["frames"], test["tp"], test["candidate_recall"]) == (2, 2, 1.0)
    assert result["results"]["5px"]["train"]["frames"] == 4
    assert "val" not in result["results"]["5px"]


def test_tracknet_yolo_dataset_keeps_games_apart(tmp_path):
    from tennis_ai.training import prepare_tracknet_ball

    make_game(tmp_path / "src", 1, [(1, 640, 360), (0, "", ""), (3, 10, 10), (1, 2, 2)])
    make_game(tmp_path / "src", 9, [(1, 100, 100)])
    data, audit = prepare_tracknet_ball(tmp_path / "src", tmp_path / "yolo", stride=1)
    assert audit["counts"]["train"] == {"images": 3, "balls": 2}  # occluded frame dropped
    assert audit["counts"]["test"] == {"images": 1, "balls": 1}
    labels = tmp_path / "yolo" / "train" / "labels"
    assert (labels / "g1_Clip1_0001.txt").read_text() == ""  # negative frame
    edge = (labels / "g1_Clip1_0003.txt").read_text().split()
    assert float(edge[1]) >= 8 / 1280  # box clamped inside the frame
    assert (tmp_path / "yolo" / "train" / "images" / "g1_Clip1_0000.jpg").is_symlink()
    assert "val" in data.read_text()
