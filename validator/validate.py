#!/usr/bin/env python3
"""Validate the rule-detectable faults in a lab delivery."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pngutil  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def add_error(errors: set[tuple[str, str]], kind: str, target: str) -> None:
    errors.add((kind, target))


def box_iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union if union > 0 else 0.0


def collect_candidates(delivery: Path) -> list[dict]:
    manifest = json.loads((delivery / "manifest.json").read_text(encoding="utf-8"))["items"]
    classes = {}
    for line in (delivery / "classes.txt").read_text(encoding="utf-8").splitlines():
        class_id, name = line.split(maxsplit=1)
        classes[int(class_id)] = name.strip()

    panoptic = json.loads((delivery / "panoptic.json").read_text(encoding="utf-8"))
    category_names = {category["id"]: category["name"] for category in panoptic["categories"]}
    thing_ids = {category["id"] for category in panoptic["categories"] if category.get("isthing")}
    image_info = {Path(image["file_name"]).stem: image for image in panoptic["images"]}
    annotation_info = {
        Path(annotation["file_name"]).stem: annotation
        for annotation in panoptic["annotations"]
    }

    candidates: dict[tuple[str, str], dict] = {}

    def add(kind: str, image: str, evidence: dict) -> None:
        key = (kind, image)
        if key not in candidates:
            candidates[key] = {"type": kind, "target": image, "evidence": []}
        candidates[key]["evidence"].append(evidence)

    for image_stem, item in manifest.items():
        image = image_info.get(image_stem)
        annotation = annotation_info.get(image_stem)
        label_rel = item.get("label")
        mask_rel = item.get("mask")
        if not image or not annotation or not label_rel or not mask_rel:
            continue
        label_path, mask_path = delivery / label_rel, delivery / mask_rel
        if not label_path.is_file() or not mask_path.is_file():
            continue
        width, height = image["width"], image["height"]

        boxes = []
        for line in label_path.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if not fields:
                continue
            try:
                class_id = int(float(fields[0]))
                center_x, center_y, box_width, box_height = map(float, fields[1:5])
            except (ValueError, IndexError):
                continue
            if class_id not in classes or box_width <= 0 or box_height <= 0:
                continue
            x1 = max(0, int((center_x - box_width / 2) * width))
            y1 = max(0, int((center_y - box_height / 2) * height))
            x2 = min(width, int((center_x + box_width / 2) * width + 0.999999))
            y2 = min(height, int((center_y + box_height / 2) * height + 0.999999))
            boxes.append({
                "class_id": class_id,
                "class": classes[class_id],
                "bbox": ((center_x - box_width / 2) * width, (center_y - box_height / 2) * height,
                         (center_x + box_width / 2) * width, (center_y + box_height / 2) * height),
                "region": (x1, y1, x2, y2),
            })

        mask_width, mask_height, pixels = pngutil.read_rgb(mask_path)
        if (mask_width, mask_height) != (width, height):
            continue

        segments = {
            segment["id"]: {
                "category_id": segment.get("category_id"),
                "class": category_names.get(segment.get("category_id")),
                "iscrowd": segment.get("iscrowd", 0),
                "area": 0,
                "bbox": [width, height, -1, -1],
            }
            for segment in annotation["segments_info"]
        }
        for y in range(height):
            row_offset = y * width * 3
            for x in range(width):
                segment_id = pngutil.segment_id(pixels, row_offset + x * 3)
                segment = segments.get(segment_id)
                if segment is not None:
                    segment["area"] += 1
                    segment["bbox"][0] = min(segment["bbox"][0], x)
                    segment["bbox"][1] = min(segment["bbox"][1], y)
                    segment["bbox"][2] = max(segment["bbox"][2], x + 1)
                    segment["bbox"][3] = max(segment["bbox"][3], y + 1)

        overlaps: dict[tuple[int, int], int] = {}
        for box_index, box in enumerate(boxes):
            x1, y1, x2, y2 = box["region"]
            hit_counts: Counter[int] = Counter()
            for y in range(y1, y2):
                row_offset = y * width * 3
                for x in range(x1, x2):
                    segment_id = pngutil.segment_id(pixels, row_offset + x * 3)
                    if segment_id in segments:
                        hit_counts[segment_id] += 1
            for segment_id, count in hit_counts.items():
                overlaps[(box_index, segment_id)] = count

        thing_segments = [
            (segment_id, segment) for segment_id, segment in segments.items()
            if segment["category_id"] in thing_ids and not segment["iscrowd"] and segment["area"] >= 512
        ]
        for segment_id, segment in thing_segments:
            if segment["area"] == 0:
                continue
            segment_bbox = tuple(float(value) for value in segment["bbox"])
            if segment_bbox[2] <= segment_bbox[0] or segment_bbox[3] <= segment_bbox[1]:
                continue

            scored = []
            for box_index, box in enumerate(boxes):
                overlap = overlaps.get((box_index, segment_id), 0)
                iou = box_iou(box["bbox"], segment_bbox)
                scored.append((max(iou, overlap / segment["area"]), box_index, iou, overlap))
            scored.sort(reverse=True)

            same_class = [
                row for row in scored
                if boxes[row[1]]["class"] == segment["class"]
            ]
            other_class = [
                row for row in scored
                if boxes[row[1]]["class"] != segment["class"]
            ]
            if other_class and other_class[0][0] >= 0.55 and (
                not same_class or other_class[0][0] >= same_class[0][0] + 0.15
            ):
                _, box_index, iou, overlap = other_class[0]
                box = boxes[box_index]
                add("class_disagreement", image_stem, {
                    "detection_class": box["class"],
                    "panoptic_class": segment["class"],
                    "possible_types": ["class_swap", "category_swap"],
                    "bbox_iou": round(iou, 3),
                    "mask_pixels_in_box": overlap,
                    "segment_id": segment_id,
                })
                continue

            if same_class and same_class[0][0] >= 0.2:
                _, box_index, iou, overlap = same_class[0]
                box = boxes[box_index]
                coverage = overlap / segment["area"]
                if segment["area"] >= 1024 and coverage < 0.55 and iou < 0.5 and overlap >= 128:
                    add("bbox_drift", image_stem, {
                        "class": segment["class"],
                        "bbox_iou": round(iou, 3),
                        "mask_coverage": round(coverage, 3),
                        "segment_id": segment_id,
                    })

                class_hits = []
                for idx, candidate_box in enumerate(boxes):
                    count = overlaps.get((idx, segment_id), 0)
                    rx1, ry1, rx2, ry2 = candidate_box["region"]
                    box_area = max(1, (rx2 - rx1) * (ry2 - ry1))
                    if (
                        candidate_box["class"] == segment["class"]
                        and count >= max(256, int(segment["area"] * 0.2))
                        and count / box_area >= 0.45
                    ):
                        class_hits.append((idx, count))
                distinct_boxes = [
                    (first, second) for offset, first in enumerate(class_hits)
                    for second in class_hits[offset + 1:]
                    if box_iou(boxes[first[0]]["bbox"], boxes[second[0]]["bbox"]) < 0.5
                ]
                if distinct_boxes:
                    add("instance_merge", image_stem, {
                        "class": segment["class"],
                        "segment_id": segment_id,
                        "detection_boxes": len(class_hits),
                        "mask_pixels_in_boxes": [count for _, count in class_hits],
                    })
            elif segment["area"] >= 1024:
                add("missing_box", image_stem, {
                    "panoptic_class": segment["class"],
                    "segment_area": segment["area"],
                    "segment_id": segment_id,
                })

    return [
        {**candidate, "evidence": candidate["evidence"][:5]}
        for _, candidate in sorted(candidates.items())
    ]


def validate(delivery: Path) -> set[tuple[str, str]]:
    if not delivery.is_dir():
        raise SystemExit(f"Không thấy thư mục delivery: {delivery}")

    errors: set[tuple[str, str]] = set()

    manifest_path = delivery / "manifest.json"
    metadata_path = delivery / "metadata.json"
    jobs_path = delivery / "jobs.csv"
    classes_path = delivery / "classes.txt"
    panoptic_path = delivery / "panoptic.json"

    required = [manifest_path, metadata_path, jobs_path, classes_path, panoptic_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Thiếu file bắt buộc trong delivery: " + ", ".join(missing))

    manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest_doc["items"]
    metadata_doc = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata = {row["image"]: row for row in metadata_doc["items"]}
    jobs = {row["job_id"]: row for row in read_csv(jobs_path)}

    scene_splits: dict[str, set[str]] = {}
    for image_stem, item in items.items():
        meta = metadata.get(image_stem)
        if meta:
            scene_splits.setdefault(meta["scene_id"], set()).add(meta["split"])
            job = jobs.get(meta["job_id"])
            if job and meta["guideline_version"] != job["guideline"]:
                add_error(errors, "guideline_mismatch", image_stem)

        image_rel = item.get("image")
        if not image_rel:
            continue
        image_path = delivery / image_rel
        if not image_path.is_file():
            add_error(errors, "missing_image", image_stem)
            continue
        if sha256(image_path) != item.get("image_sha256"):
            add_error(errors, "wrong_hash", image_stem)

        label_rel = item.get("label")
        if not label_rel:
            continue
        label_path = delivery / label_rel
        if not label_path.is_file():
            continue

        try:
            image_width, image_height = png_or_jpeg_size(delivery / image_rel)
        except (OSError, ValueError):
            image_width, image_height = 1, 1

        boxes: list[list[str]] = []
        for line in label_path.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if not fields:
                continue
            try:
                class_id = int(float(fields[0]))
                x, y, w, h = map(float, fields[1:5])
            except (ValueError, IndexError):
                add_error(errors, "invalid_class", image_stem)
                continue

            if not 0 <= class_id < 80:
                add_error(errors, "invalid_class", image_stem)
            if x - w / 2 < -0.01 or y - h / 2 < -0.01 or x + w / 2 > 1.01 or y + h / 2 > 1.01:
                add_error(errors, "bbox_out_of_bounds", image_stem)

            boxes.append([str(class_id), str(x), str(y), str(w), str(h)])

        if image_width > 1 and image_height > 1:
            for index, first in enumerate(boxes):
                class_a, x_a, y_a, w_a, h_a = first
                center_x_a = float(x_a) * image_width
                center_y_a = float(y_a) * image_height
                width_a = float(w_a) * image_width
                height_a = float(h_a) * image_height

                for second in boxes[index + 1:]:
                    class_b, x_b, y_b, w_b, h_b = second
                    if class_a != class_b:
                        continue
                    center_x_b = float(x_b) * image_width
                    center_y_b = float(y_b) * image_height
                    width_b = float(w_b) * image_width
                    height_b = float(h_b) * image_height

                    dx = abs(center_x_a - center_x_b)
                    dy = abs(center_y_a - center_y_b)
                    same_size = abs(width_a - width_b) <= 2.0 and abs(height_a - height_b) <= 2.0
                    close_center = 0.7 <= dx <= 2.1 or 0.7 <= dy <= 2.1
                    close_center = close_center and dx <= 2.1 and dy <= 2.1
                    if same_size and close_center:
                        add_error(errors, "duplicate_box", image_stem)
                        break

    for scene_id, splits in scene_splits.items():
        if len(splits) > 1:
            add_error(errors, "scene_leak", scene_id)

    panoptic = json.loads(panoptic_path.read_text(encoding="utf-8"))
    category_ids = {category["id"] for category in panoptic["categories"]}
    thing_ids = {category["id"] for category in panoptic["categories"] if category.get("isthing")}
    annotation_by_mask = {
        Path(annotation["file_name"]).stem: annotation
        for annotation in panoptic["annotations"]
    }

    for image_stem, item in items.items():
        mask_rel = item.get("mask")
        if not mask_rel:
            continue
        mask_path = delivery / mask_rel
        if not mask_path.is_file():
            continue

        annotation = annotation_by_mask.get(Path(mask_path.name).stem)
        if annotation:
            for segment in annotation["segments_info"]:
                category_id = segment.get("category_id")
                if category_id not in category_ids:
                    add_error(errors, "invalid_category_id", image_stem)

        width, height, pixels = pngutil.read_rgb(mask_path)
        del height
        counts: dict[int, int] = {}
        for index in range(0, len(pixels), 3):
            segment_id = pngutil.segment_id(pixels, index)
            if segment_id:
                counts[segment_id] = counts.get(segment_id, 0) + 1

        if annotation:
            for segment in annotation["segments_info"]:
                category_id = segment.get("category_id")
                declared_area = segment.get("area")
                actual_area = counts.get(segment["id"], 0)
                if (
                    category_id in thing_ids
                    and isinstance(declared_area, (int, float))
                    and actual_area < declared_area
                    and declared_area - actual_area >= 30
                ):
                    add_error(errors, "thing_overlap", image_stem)
                    break

    return errors


def png_or_jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height, _ = pngutil.read_rgb(path)
        return width, height
    if data[:2] != b"\xff\xd8":
        raise ValueError("unsupported image format")

    position = 2
    while position + 9 < len(data):
        if data[position] != 0xff:
            position += 1
            continue
        marker = data[position + 1]
        if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
            position += 2
            continue
        length = int.from_bytes(data[position + 2:position + 4], "big")
        if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
            height = int.from_bytes(data[position + 5:position + 7], "big")
            width = int.from_bytes(data[position + 7:position + 9], "big")
            return width, height
        position += 2 + length
    raise ValueError("JPEG dimensions not found")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate rule-detectable delivery faults")
    parser.add_argument("delivery", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--candidates", type=Path)
    args = parser.parse_args()

    errors = validate(args.delivery)
    document = {"errors": [{"type": kind, "target": target} for kind, target in sorted(errors)]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    if args.candidates:
        args.candidates.parent.mkdir(parents=True, exist_ok=True)
        candidates = collect_candidates(args.delivery)
        args.candidates.write_text(json.dumps({"candidates": candidates}, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(candidates)} cross-check candidates to {args.candidates}")

    print(f"Wrote {len(errors)} rule-detectable findings to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
