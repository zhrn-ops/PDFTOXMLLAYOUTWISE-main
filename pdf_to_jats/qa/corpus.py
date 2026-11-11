"""Immutable corpus releases and explicit reference-review records."""
from datetime import date
import re
from pathlib import Path
from .readers import canonical, sha256, read_json, read_artifact


def require(condition, message):
    if not condition:
        raise ValueError(message)


def artifact(record):
    require(isinstance(record, dict) and isinstance(record.get("path"), str)
            and re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))), "Invalid artifact record")


def validate_manifest(manifest):
    require(isinstance(manifest, dict) and manifest.get("contract_version") == 1, "Unsupported manifest contract")
    for key in ("corpus_id", "manifest_version"):
        require(isinstance(manifest.get(key), str) and manifest[key].strip(), f"Missing {key}")
    require(manifest.get("kind") in {"reviewed", "synthetic"}, "Corpus kind must be reviewed or synthetic")
    threshold = manifest.get("coverage_threshold", 0.95)
    require(isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and 0 <= threshold <= 1,
            "Coverage threshold must be in [0, 1]")
    thresholds = manifest.get("coverage_thresholds", {})
    require(isinstance(thresholds, dict) and set(thresholds) <= {"authors", "affiliations", "reading_order"}, "Unknown coverage threshold")
    for value in thresholds.values():
        require(isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1, "Invalid coverage threshold")
    articles = manifest.get("articles")
    require(isinstance(articles, list) and articles, "Corpus must contain articles")
    ids = set()
    for article in articles:
        require(isinstance(article, dict), "Invalid article")
        key = article.get("id")
        require(isinstance(key, str) and key and key not in ids, "Missing or duplicate article ID")
        ids.add(key)
        artifact(article.get("pdf"))
        artifact(article.get("reference"))
        require(article.get("format") in {"JATS", "ANI"}, "Unsupported reference format")
        require(isinstance(article.get("scope"), str) and article["scope"].strip(), "Document evaluation scope is required")
        review = article.get("review", {})
        require(isinstance(review, dict), "Review must be an object")
        require(review.get("status") in {"draft", "in_review", "approved", "rejected"}, "Invalid review status")
        require(isinstance(review.get("reference_version"), str) and review["reference_version"], "Reference version required")
        issues = review.get("ambiguities", [])
        require(isinstance(issues, list), "Ambiguities must be a list")
        if review["status"] == "approved":
            require(isinstance(review.get("reviewer"), str) and review["reviewer"].strip(), "Reviewer identity required")
            date.fromisoformat(review.get("date", ""))
            require(review.get("reference_sha256") == article["reference"]["sha256"], "Approval must bind to reference hash")
            for issue in issues:
                require(isinstance(issue, dict), "Ambiguities must contain objects")
                require(all(isinstance(issue.get(k), str) and issue[k].strip()
                            for k in ("question", "resolution", "resolved_by", "date")), "Unresolved ambiguity")
                date.fromisoformat(issue["date"])
        if "annotations" in article:
            artifact(article["annotations"])
    return manifest


def freeze_manifest(source, destination):
    """Publish once; an existing version cannot be overwritten, even identically."""
    manifest = validate_manifest(read_json(source))
    require("release_sha256" not in manifest, "Source is already frozen")
    for article in manifest["articles"]:
        for field in ("pdf", "reference", "annotations"):
            if field in article:
                read_artifact(Path(source).parent, article[field])
    digest = sha256(canonical(manifest))
    manifest["release_sha256"] = digest
    destination = Path(destination)
    require(destination.parent.resolve() == Path(source).parent.resolve(), "Freeze beside source to preserve relative paths")
    if destination.exists():
        raise FileExistsError(destination)
    for sibling in destination.parent.glob("*.json"):
        if sibling == Path(source):
            continue
        try:
            previous = read_json(sibling)
        except (ValueError, OSError):
            continue
        if isinstance(previous, dict) and previous.get("release_sha256"):
            require((previous.get("corpus_id"), previous.get("manifest_version")) !=
                    (manifest["corpus_id"], manifest["manifest_version"]),
                    "Corpus version already published in this directory; increment manifest_version")
    with destination.open("xb") as stream:
        stream.write(canonical(manifest) + b"\n")
    return digest


def load_release(path):
    manifest = read_json(path)
    require(isinstance(manifest, dict), "Manifest must be an object")
    digest = manifest.pop("release_sha256", None)
    require(digest == sha256(canonical(manifest)), "Manifest is not frozen or was modified")
    validate_manifest(manifest)
    manifest["release_sha256"] = digest
    return manifest
