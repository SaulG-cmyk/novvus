"""Per-module translation catalogs and the `_()` helper (docs/I18N.md).

Adapted from the gettext pattern: the source language is es-MX (so an
untranslated string returns itself), and each module ships JSON catalogs under
`i18n/{locale}.json` mapping source string → translation. Lookup falls back
from a regional locale (`en-US`) to its base (`en`) to the source string, so a
missing translation is never an error."""

from __future__ import annotations

import json
from pathlib import Path

from novvus_sdk.context import DEFAULT_LOCALE, current_context

Catalog = dict[str, str]


def _base_locale(locale: str) -> str:
    """`en-US` → `en`; already-base locales are returned unchanged."""
    return locale.split("-", 1)[0]


class Translator:
    """Loads a module's translation catalogs and resolves messages by locale."""

    def __init__(self, catalogs: dict[str, Catalog]) -> None:
        # Keys are normalized to lowercase so lookup is case-insensitive on the
        # locale tag (es-MX vs es-mx).
        self._catalogs = {loc.lower(): cat for loc, cat in catalogs.items()}

    @classmethod
    def load(cls, directory: Path) -> Translator:
        """Load every `*.json` catalog in `directory` (missing dir → empty)."""
        catalogs: dict[str, Catalog] = {}
        if directory.is_dir():
            for path in sorted(directory.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if isinstance(data, dict):
                    catalogs[path.stem] = {str(k): str(v) for k, v in data.items()}
        return cls(catalogs)

    def gettext(self, message: str, locale: str | None = None) -> str:
        """Translate `message` into `locale` (or the current request locale).

        Resolution order: exact locale → base locale → source string. The
        source language is es-MX, so es-MX strings pass through untranslated."""
        loc = (locale or _current_locale()).lower()
        for candidate in (loc, _base_locale(loc)):
            catalog = self._catalogs.get(candidate)
            if catalog and message in catalog:
                return catalog[message]
        return message


def _current_locale() -> str:
    """The request locale, or the platform default outside a request."""
    try:
        return current_context().locale
    except RuntimeError:
        return DEFAULT_LOCALE
