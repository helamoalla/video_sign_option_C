def compute_language_statistics(avatar_debug: dict):
    stats = {}

    for lang, data in avatar_debug.items():
        glosses = data.get("glosses_found", [])
        error = data.get("error")

        stats[lang] = {
            "glosses_found_count": len(glosses),
            "glosses_found": glosses,
            "has_avatar": data.get("avatar_url") is not None,
            "error": error,
            "coverage_status": "ok" if glosses and not error else "missing_or_partial"
        }

    return stats